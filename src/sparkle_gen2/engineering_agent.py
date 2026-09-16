from __future__ import annotations
from dataclasses import dataclass, field, asdict

@dataclass(slots=True)
class EngineeringRun:
    project_name:str
    status:str='PLANNED'
    completed:list[str]=field(default_factory=list)
    evidence:dict=field(default_factory=dict)
    blocker:str|None=None
    def to_dict(self):return asdict(self)

class AutonomousEngineeringWorkflow:
    """Bounded engineering workflow; never bypasses workflow approval/tool policy."""
    def __init__(self,workflow,*,max_operations:int=4):
        if not 1<=max_operations<=8:raise ValueError('max_operations out of range')
        self.workflow=workflow;self.max_operations=max_operations
    def execute(self,project_name,files,checks,*,approved=False):
        run=EngineeringRun(project_name);ops=0
        if not approved:
            run.status='WAITING_FOR_APPROVAL';run.blocker='approval_required';return run
        phases=(
            ('scaffold',lambda:self.workflow.scaffold(project_name,files,approved=True)),
            ('verify',lambda:self.workflow.verify_workspace(project_name,checks,approved=True)),
            ('test',lambda:self.workflow.test_workspace(project_name,approved=True)),
            ('package',lambda:self.workflow.package_artifact(project_name,approved=True)),
        )
        for phase,action in phases:
            if ops>=self.max_operations:
                run.status='PAUSED';run.blocker='operation_budget_exhausted';return run
            ops+=1
            try:result=action()
            except Exception as exc:
                run.status='EXTERNALLY_BLOCKED' if phase=='test' and 'workspace_test' in str(exc) else 'BLOCKED'
                run.blocker=f'{phase}:{type(exc).__name__}:{str(exc)[:160]}'
                return run
            verification=result.get('verification',{}) if isinstance(result,dict) else {}
            if phase in {'verify','test'} and verification.get('verified') is not True:
                run.status='BLOCKED';run.blocker=f'{phase}:unverified';return run
            run.completed.append(phase);run.evidence[phase]=result
        run.status='COMPLETE';return run
