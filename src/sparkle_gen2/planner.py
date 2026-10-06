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

        # Cycle75: canonicalize and validate goal success criteria at the
        # planner-model boundary, before PlanProposal construction.
        raw_criteria = raw.get('success_criteria')
        if not isinstance(raw_criteria, list) or not raw_criteria:
            raise RuntimeError('planner_success_criteria_invalid')

        normalized_criteria = []
        for criterion in raw_criteria:
            if not isinstance(criterion, dict):
                raise RuntimeError('planner_goal_criterion_not_object')

            if (
                'description' not in criterion
                or 'verification_method' not in criterion
            ):
                raise RuntimeError(
                    'planner_goal_criterion_missing_required_field'
                )

            description = criterion['description']
            verification_method = criterion['verification_method']

            if not isinstance(description, str) or not description.strip():
                raise RuntimeError(
                    'planner_goal_criterion_invalid_description'
                )

            if (
                not isinstance(verification_method, str)
                or not verification_method.strip()
            ):
                raise RuntimeError(
                    'planner_goal_criterion_invalid_verification_method'
                )

            normalized_criteria.append({
                'description': description.strip(),
                'verification_method': verification_method.strip(),
            })

        raw['success_criteria'] = normalized_criteria

        # Cycle76: deterministic high-confidence routing guard.
        #
        # The model plans the task, but these two unambiguous routes are
        # enforced by Gen-2 after parsing so model tool preference cannot
        # swap personal project discovery with repository inspection.
        goal_request=str(goal.to_dict().get('user_request','')).strip()
        request_lower=goal_request.lower()

        repository_markers=(
            'repository',
            'repo',
            'codebase',
            'source tree',
            'repository structure',
            'important files',
            'file structure',
            'current code',
            'code files',
            'sparkle-gen2',
        )

        repository_request=any(
            marker in request_lower
            for marker in repository_markers
        )

        personal_project_request=(
            ('my ' in request_lower and 'project' in request_lower)
            or 'personal project' in request_lower
            or 'personal projects' in request_lower
        )

        steps=raw.get('steps',[])

        if (
            isinstance(steps,list)
            and len(steps)==1
            and isinstance(steps[0],dict)
        ):
            step=steps[0]

            if (
                personal_project_request
                and not repository_request
                and 'project_search' in available_capabilities
            ):
                step['required_capabilities']=['project_search']
                step['arguments']={
                    'query':goal_request,
                    'limit':10,
                }

            elif (
                repository_request
                and 'engineering_inspect' in available_capabilities
            ):
                structure_request=any(
                    marker in request_lower
                    for marker in (
                        'repository structure',
                        'important files',
                        'file structure',
                        'source tree',
                        'list the files',
                        'file listing',
                    )
                )

                if structure_request:
                    step['required_capabilities']=['engineering_inspect']
                    step['arguments']={
                        'operation':'snapshot',
                    }


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
