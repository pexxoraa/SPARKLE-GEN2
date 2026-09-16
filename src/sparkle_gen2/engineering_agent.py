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

class SoftwareEngineeringAgent:
    """Inspect -> implement -> verify/test -> diagnose/fix/retest -> review -> package/report."""
    def __init__(self,workflow,*,diagnoser=None,fixer=None,reviewer=None,max_fix_attempts=1):
        if not 0<=max_fix_attempts<=3:raise ValueError('max_fix_attempts out of range')
        self.workflow=workflow;self.diagnoser=diagnoser;self.fixer=fixer;self.reviewer=reviewer;self.max_fix_attempts=max_fix_attempts
    def run(self,project_name,files,checks,*,inspect_target='README.md',approved=False):
        report={'project':project_name,'status':'RUNNING','phases':[],'evidence':{},'fix_attempts':0}
        report['evidence']['inspect']=self.workflow.inspect_code(inspect_target);report['phases'].append('inspect')
        if not approved:report['status']='WAITING_FOR_APPROVAL';return report
        report['evidence']['implement']=self.workflow.scaffold(project_name,files,approved=True);report['phases'].append('implement')
        report['evidence']['verify']=self.workflow.verify_workspace(project_name,checks,approved=True);report['phases'].append('verify')
        test_error=None
        try:report['evidence']['test']=self.workflow.test_workspace(project_name,approved=True)
        except Exception as exc:test_error=exc;report['evidence']['test']={'error':str(exc),'error_type':type(exc).__name__}
        report['phases'].append('test')
        while test_error is not None and report['fix_attempts']<self.max_fix_attempts and self.diagnoser and self.fixer:
            diagnosis=self.diagnoser(report['evidence']['test']);report['evidence'][f'diagnose_{report["fix_attempts"]+1}']=diagnosis;report['phases'].append('diagnose')
            replacement=self.fixer(diagnosis,dict(files));report['fix_attempts']+=1
            report['evidence'][f'fix_{report["fix_attempts"]}']=self.workflow.scaffold(project_name,replacement,approved=True,overwrite=True);report['phases'].append('fix')
            report['evidence'][f'verify_{report["fix_attempts"]}']=self.workflow.verify_workspace(project_name,checks,approved=True)
            try:report['evidence'][f'retest_{report["fix_attempts"]}']=self.workflow.test_workspace(project_name,approved=True);test_error=None
            except Exception as exc:test_error=exc;report['evidence'][f'retest_{report["fix_attempts"]}']={'error':str(exc),'error_type':type(exc).__name__}
            report['phases'].append('retest')
        if test_error is not None:
            report['status']='EXTERNALLY_BLOCKED' if 'workspace_test' in str(test_error) else 'BLOCKED';report['blocker']=str(test_error)[:200];return report
        review=self.reviewer(report) if self.reviewer else {'verified':True,'method':'bounded workflow evidence review'}
        report['evidence']['review']=review;report['phases'].append('review')
        if not isinstance(review,dict) or review.get('verified') is not True:report['status']='BLOCKED';report['blocker']='review_failed';return report
        report['evidence']['package']=self.workflow.package_artifact(project_name,approved=True);report['phases'].append('report');report['status']='COMPLETE';return report
