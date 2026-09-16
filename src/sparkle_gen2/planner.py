from __future__ import annotations
import json,uuid
from typing import Any,Protocol
from .models import Goal,ModelProvenance,PlanProposal,PlanProposalStep,RiskLevel
from .core_time import now

class PlannerError(RuntimeError): pass

class PlannerModel(Protocol):
    def propose(self,goal:Goal,context:dict[str,Any],available_capabilities:list[str])->tuple[PlanProposal,ModelProvenance]: ...

class Gen1PlannerModel:
    def __init__(self,gateway): self.gateway=gateway
    def propose(self,goal:Goal,context:dict[str,Any],available_capabilities:list[str]):
        payload=self.gateway.plan(goal.to_dict(),context,available_capabilities)
        raw=payload['proposal']; prov=payload['provenance']
        try:
            steps=[PlanProposalStep(**s) for s in raw['steps']]
            proposal=PlanProposal(
                proposal_id=raw.get('proposal_id') or uuid.uuid4().hex,
                goal_id=goal.goal_id,
                steps=steps,
                success_criteria=raw['success_criteria'],risk=raw['risk'],
                confidence=float(raw['confidence']),unresolved_questions=list(raw.get('unresolved_questions',[])),
                created_at=now(),
            )
            provenance=ModelProvenance(**prov)
        except Exception as exc:
            raise PlannerError(f'invalid_structured_output:{type(exc).__name__}') from exc
        return proposal,provenance

class StaticPlanner:
    """Test-only injected planner; never selected automatically in production."""
    def __init__(self,proposal:PlanProposal): self.proposal=proposal
    def propose(self,goal,context,available_capabilities):
        p=self.proposal; p.goal_id=goal.goal_id
        return p,ModelProvenance('test-request','test','test-model','reasoning',['planning','reasoning'],'injected_test_planner','HEALTHY',fallback=False)
