from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

class GoalStatus(StrEnum):
    CREATED='CREATED'; UNDERSTANDING='UNDERSTANDING'; PLANNED='PLANNED'; AUTHORIZED='AUTHORIZED'
    EXECUTING='EXECUTING'; WAITING='WAITING'; VERIFYING='VERIFYING'; BLOCKED='BLOCKED'
    COMPLETED='COMPLETED'; FAILED='FAILED'; CANCELLED='CANCELLED'

class StepStatus(StrEnum):
    PENDING='PENDING'; EXECUTING='EXECUTING'; WAITING='WAITING'; VERIFIED='VERIFIED'; FAILED='FAILED'; BLOCKED='BLOCKED'

class RiskLevel(StrEnum): LOW='LOW'; MEDIUM='MEDIUM'; HIGH='HIGH'; CRITICAL='CRITICAL'
class ApprovalStatus(StrEnum): PENDING='PENDING'; APPROVED='APPROVED'; REJECTED='REJECTED'; EXPIRED='EXPIRED'; CANCELLED='CANCELLED'
class PermissionStatus(StrEnum): ACTIVE='ACTIVE'; REVOKED='REVOKED'; EXPIRED='EXPIRED'
class PermissionEffect(StrEnum): ALLOW='ALLOW'; REQUIRE_APPROVAL='REQUIRE_APPROVAL'; DENY='DENY'
class CriterionStatus(StrEnum): PENDING='PENDING'; SATISFIED='SATISFIED'; FAILED='FAILED'; BLOCKED='BLOCKED'

@dataclass(slots=True)
class Goal:
    goal_id:str; user_request:str; normalized_objective:str
    constraints:list[str]=field(default_factory=list); priority:int=5; deadline:str|None=None
    success_criteria:list[str]=field(default_factory=list); risk_level:str='LOW'
    context_requirements:list[str]=field(default_factory=list); status:GoalStatus=GoalStatus.CREATED
    plan_id:str|None=None; parent_goal_id:str|None=None; created_at:str=''; updated_at:str=''; user_id:str='user'
    metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):
        d=asdict(self); d['status']=self.status.value; return d

@dataclass(slots=True)
class PlanProposalStep:
    step_id:str; objective:str; required_capabilities:list[str]; depends_on:list[str]
    success_criteria:list[str]; arguments:dict[str,Any]=field(default_factory=dict)
    timeout_seconds:int=30; retry_limit:int=1

@dataclass(slots=True)
class PlanProposal:
    proposal_id:str; goal_id:str; steps:list[PlanProposalStep]; success_criteria:list[dict[str,str]]
    risk:str; confidence:float; unresolved_questions:list[str]; created_at:str
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class ModelProvenance:
    request_id:str; provider:str; model:str; capability:str; requested_capabilities:list[str]
    selection_reason:str; health:str; trace_id:str|None=None; fallback:bool=False
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class PlanStep:
    step_id:str; description:str; dependencies:list[str]; required_capabilities:list[str]
    preferred_tool:str; preferred_model_capability:str; risk:str; authorization_requirement:str
    timeout_seconds:int; retry_limit:int; success_criteria:list[str]; verification_method:str
    rollback_strategy:str|None; arguments:dict[str,Any]=field(default_factory=dict)
    status:StepStatus=StepStatus.PENDING; attempts:int=0; result:dict[str,Any]|None=None
    def to_dict(self):
        d=asdict(self); d['status']=self.status.value; return d

@dataclass(slots=True)
class Plan:
    plan_id:str; goal_id:str; steps:list[PlanStep]; created_at:str
    proposal_id:str|None=None
    def to_dict(self):
        return {'plan_id':self.plan_id,'goal_id':self.goal_id,'created_at':self.created_at,'proposal_id':self.proposal_id,'steps':[s.to_dict() for s in self.steps]}

@dataclass(slots=True)
class TaskRun:
    task_run_id:str; goal_id:str; current_step:str|None; completed_steps:list[str]; failed_steps:list[str]
    pending_steps:list[str]; artifacts:list[str]; approvals:list[str]; events:list[dict[str,Any]]
    started_at:str; updated_at:str; deadline:str|None; status:str
    trace_id:str|None=None
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class Permission:
    permission_id:str; subject:str; capability:str; scope:str; effect:PermissionEffect; status:PermissionStatus
    granted_by:str; created_at:str; expires_at:str|None=None; metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):
        d=asdict(self); d['effect']=self.effect.value; d['status']=self.status.value; return d

@dataclass(slots=True)
class RiskEvaluation:
    risk_id:str; action:str; capability:str; level:RiskLevel; rationale:str; evaluated_by:str
    timestamp:str; required_authorization:str
    def to_dict(self):
        d=asdict(self); d['level']=self.level.value; return d

@dataclass(slots=True)
class Approval:
    approval_id:str; goal_id:str; task_run_id:str; step_id:str; action:str; capability:str; risk:RiskLevel
    requested_at:str; expires_at:str|None; status:ApprovalStatus; requested_scope:str
    approved_by:str|None=None; decision_at:str|None=None
    def to_dict(self):
        d=asdict(self); d['risk']=self.risk.value; d['status']=self.status.value; return d

@dataclass(slots=True)
class GoalSuccessCriterion:
    criterion_id:str; goal_id:str; description:str; verification_method:str; status:CriterionStatus
    evidence:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):
        d=asdict(self); d['status']=self.status.value; return d
