from __future__ import annotations
import re,uuid
from .models import Plan,PlanProposal,PlanStep
from .policy import PolicyEngine

ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')

class PlanValidationError(ValueError): pass

class PlanValidator:
    def __init__(self,available_tools:set[str],policy:PolicyEngine):
        self.available_tools=set(available_tools); self.policy=policy
    def validate(self,proposal:PlanProposal,*,subject:str,timestamp:str)->tuple[Plan,list[tuple]]:
        if not proposal.steps: raise PlanValidationError('plan has no steps')
        if proposal.risk not in {'LOW','MEDIUM','HIGH','CRITICAL'}: raise PlanValidationError('invalid proposed risk')
        if proposal.unresolved_questions: raise PlanValidationError('unresolved_questions')
        if not 0<=proposal.confidence<=1: raise PlanValidationError('invalid confidence')
        ids=set()
        for s in proposal.steps:
            if not ID.fullmatch(s.step_id): raise PlanValidationError('invalid step id')
            if s.step_id in ids: raise PlanValidationError('duplicate step id')
            ids.add(s.step_id)
            if len(s.required_capabilities)!=1: raise PlanValidationError('each step requires exactly one executable capability')
            capability=s.required_capabilities[0]
            if capability not in self.available_tools: raise PlanValidationError(f'unsupported_capability:{capability}')
            if not s.success_criteria or any(not isinstance(x,str) or not x.strip() for x in s.success_criteria): raise PlanValidationError('malformed step success criteria')
            if not 1<=s.timeout_seconds<=600 or not 0<=s.retry_limit<=5: raise PlanValidationError('invalid retry/timeout policy')
        graph={s.step_id:list(s.depends_on) for s in proposal.steps}
        for key,deps in graph.items():
            if key in deps or any(d not in ids for d in deps): raise PlanValidationError('invalid dependency')
        visiting=set(); done=set()
        def visit(k):
            if k in visiting: raise PlanValidationError('dependency cycle')
            if k in done:return
            visiting.add(k)
            for d in graph[k]:visit(d)
            visiting.remove(k);done.add(k)
        for k in graph: visit(k)
        decisions=[]; steps=[]
        for s in proposal.steps:
            cap=s.required_capabilities[0]
            permission,risk=self.policy.evaluate(cap,subject,s.objective,timestamp); decisions.append((permission,risk))
            if permission.effect.value=='DENY': raise PlanValidationError(f'permission_denied:{cap}')
            steps.append(PlanStep(s.step_id,s.objective,list(s.depends_on),[cap],cap,'reasoning',risk.level.value,permission.effect.value,s.timeout_seconds,s.retry_limit,list(s.success_criteria),'gen1_observation','none',dict(s.arguments)))
        for c in proposal.success_criteria:
            if set(c)!={'description','verification_method'} or not c['description'].strip(): raise PlanValidationError('malformed goal criterion')
            method=c['verification_method']
            if method not in {'all_steps_verified','plan_persisted'} and not (method.startswith('step_verified:') and method.split(':',1)[1] in ids):
                raise PlanValidationError('unsupported verification method')
        return Plan(uuid.uuid4().hex,proposal.goal_id,steps,timestamp,proposal.proposal_id),decisions
