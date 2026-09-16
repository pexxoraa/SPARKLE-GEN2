from __future__ import annotations
from .experiments import ExperimentManager

class Gen1Workflow:
    def __init__(self,gen1):self.gen1=gen1
    def _call(self,tool,args,*,approved=False,write=False):
        if tool not in set(self.gen1.health().get('tools',[])):raise RuntimeError(f'unsupported_tool:{tool}')
        if write and not approved:raise PermissionError('approval_required')
        obs=self.gen1.invoke(tool,args)
        if not obs.ok:raise RuntimeError(f'tool_failed:{tool}')
        return {'tool':tool,'output':obs.output,'verification':obs.verification}
    def research(self,project,report=False):return self._call('research_workspace',{'project':project,'report':bool(report)})
    def inspect_code(self,path):return self._call('engineering_inspect',{'operation':'file','path':path})
    def scaffold(self,name,files,*,approved=False):return self._call('workspace_scaffold',{'project_name':name,'files':dict(files),'approved':True},approved=approved,write=True)
    def verify_workspace(self,name,checks,*,approved=False):return self._call('workspace_verify',{'project_name':name,'checks':list(checks),'approved':True},approved=approved,write=True)
    def test_workspace(self,name,*,approved=False):return self._call('workspace_test',{'project_name':name,'approved':True},approved=approved,write=True)
    def package_artifact(self,name,*,approved=False):return self._call('workspace_package',{'project_name':name,'approved':True},approved=approved,write=True)

class ResearchExperimentWorkflow:
    def __init__(self,gen1,experiments=None):self.gen1=gen1;self.experiments=experiments or ExperimentManager()
    def create_from_research(self,query,hypothesis,method):
        if 'research_workspace' not in set(self.gen1.health().get('tools',[])):raise RuntimeError('research_unavailable')
        obs=self.gen1.invoke('research_workspace',{'project':query,'report':False})
        if not obs.ok:raise RuntimeError('research_failed')
        e=self.experiments.create(hypothesis,method);self.experiments.observe(e.experiment_id,{'research':obs.output,'verification':obs.verification});return e
