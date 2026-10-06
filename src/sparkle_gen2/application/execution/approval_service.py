"""Human-approval policy and execution-grant service.

This service owns authorization decisions; PersonalAgent only coordinates the
use case. It deliberately receives the agent dependencies instead of importing
the HTTP layer or model providers.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ...domain.models import (
    ApprovalStatus,
    PermissionEffect,
    PermissionStatus,
)
from ...permission_center import PermissionCenter
from ...core_time import now


class ApprovalService:
    def __init__(self, store: Any, *, traces: Any):
        self.store = store
        self.traces = traces

    def find_for_step(self, goal_id: str, step_id: str):
        current_run=self.store.load_task_run_for_goal(goal_id)
        items = [
            a for a in self.store.approvals_for_goal(goal_id)
            if a.step_id == step_id and a.task_run_id==current_run.task_run_id
            and a.status in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
                ApprovalStatus.REJECTED,
            }
        ]
        return items[-1] if items else None

    @staticmethod
    def contains_model_authority(value: Any) -> bool:
        forbidden = {"approved", "approval_id", "grant_id", "authorization_override"}
        if isinstance(value, dict):
            return bool(forbidden.intersection(value)) or any(
                ApprovalService.contains_model_authority(v) for v in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(ApprovalService.contains_model_authority(v) for v in value)
        return False

    @staticmethod
    def exact_scope(goal: Any, step: Any) -> str:
        return json.dumps(
            {
                "user_id": goal.user_id,
                "goal_id": goal.goal_id,
                "tool": step.preferred_tool,
                "arguments": step.arguments,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def workspace_test_grant(self, goal: Any, run: Any, step: Any, approval: Any, scope: str):
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            raise PermissionError("workspace_test requires approved human authorization")
        actor = str(approval.approved_by or "").strip()
        if not actor or actor.lower() in {"model", "assistant", "nemotron", "system", "system_cancel"}:
            raise PermissionError("workspace_test requires trusted human approval")

        center = PermissionCenter(self.store, goal.goal_id)
        existing = [
            p for p in center.list(include_inactive=True)
            if p.capability == "workspace_test"
            and p.metadata.get("approval_id") == approval.approval_id
        ]
        if existing:
            grant = existing[-1]
            if (
                grant.subject != goal.user_id
                or grant.scope != scope
                or grant.metadata.get("task_run_id") != run.task_run_id
                or grant.metadata.get("step_id") != step.step_id
            ):
                raise PermissionError("workspace_test execution grant scope mismatch")
            if grant.status != PermissionStatus.ACTIVE:
                raise PermissionError("workspace_test execution grant is not active")
            return center, grant

        expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        if approval.expires_at:
            try:
                approved_expiry = datetime.fromisoformat(
                    str(approval.expires_at).replace("Z", "+00:00")
                )
                if approved_expiry.tzinfo is None:
                    approved_expiry = approved_expiry.replace(tzinfo=UTC)
                expires = min(
                    datetime.fromisoformat(expires), approved_expiry
                ).isoformat()
            except (TypeError, ValueError) as exc:
                raise PermissionError("workspace_test approval expiry invalid") from exc

        grant = center.grant(
            goal.user_id,
            "workspace_test",
            scope,
            PermissionEffect.ALLOW,
            granted_by=actor,
            expires_at=expires,
            metadata={
                "approval_id": approval.approval_id,
                "task_run_id": run.task_run_id,
                "step_id": step.step_id,
                "one_time": True,
            },
        )
        self.store.event(
            goal.goal_id,
            "workspace_test_grant_issued",
            {
                "permission_id": grant.permission_id,
                "approval_id": approval.approval_id,
                "step_id": step.step_id,
                "expires_at": grant.expires_at,
            },
            now(),
        )
        self.traces.record(
            "authorization",
            "workspace_test_grant",
            "ISSUED",
            goal_id=goal.goal_id,
            task_run_id=run.task_run_id,
            trace_id=run.trace_id,
            correlation={
                "approval_id": approval.approval_id,
                "permission_id": grant.permission_id,
                "step_id": step.step_id,
            },
            detail={"one_time": True},
        )
        return center, grant

    def decide(self, approval_id: str, decision: str, *, actor: str = "user"):
        approval = self.store.load_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("approval is not pending")
        if (
            approval.capability == "workspace_test"
            and decision == "approve"
            and str(actor).strip().lower()
            in {"model", "assistant", "nemotron", "system", "system_cancel"}
        ):
            raise PermissionError("model_cannot_approve_workspace_test")
        if approval.expires_at and self.deadline_expired(approval.expires_at):
            approval.status = ApprovalStatus.EXPIRED
            approval.decision_at = now()
            self.store.save_approval(approval)
            self.store.event(
                approval.goal_id,
                "approval_expired",
                {"approval_id": approval_id},
                now(),
            )
            raise ValueError("approval has expired")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")

        approval.status = (
            ApprovalStatus.APPROVED if decision == "approve"
            else ApprovalStatus.REJECTED
        )
        approval.approved_by = actor
        approval.decision_at = now()
        self.store.save_approval(approval)
        self.store.event(
            approval.goal_id,
            "approval_decided",
            {
                "approval_id": approval_id,
                "status": approval.status.value,
                "actor": actor,
            },
            now(),
        )
        return approval.to_dict()

    @staticmethod
    def deadline_expired(deadline: str | None) -> bool:
        if not deadline:
            return False
        try:
            value = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value <= datetime.now(UTC)
        except (TypeError, ValueError):
            return True
