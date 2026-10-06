from __future__ import annotations
from ..experiments import ExperimentManager

class ResearchExperimentPipeline:
    """Bounded research -> comparison -> candidate -> experiment -> analysis -> documentation workflow."""
    def __init__(self,gen1,executor,*,experiments=None):self.gen1=gen1;self.executor=executor;self.experiments=experiments or ExperimentManager()
    def run(self,research_project,candidates,hypothesis,method,*,approved=False,project_id=None,code_version=None,model=None,dataset=None,experiment_id=None):
        if experiment_id is not None:
            exp=self.experiments.items.get(experiment_id)
            if exp is None:raise KeyError(experiment_id)
            if exp.status=='COMPLETED':raise ValueError('experiment closed')
            comparison=list(exp.configuration.get('comparison',[]));selected=exp.configuration.get('candidate')
            if not selected:raise ValueError('persisted experiment missing selected candidate')
        else:
            if not candidates:raise ValueError('candidate methods required')
            obs=self.gen1.invoke('research_workspace',{'project':research_project,'report':False})
            if not obs.ok or obs.verification.get('verified') is not True:raise RuntimeError('research_unverified')
            comparison=[{'candidate':str(c),'rank':i+1} for i,c in enumerate(candidates)]
            selected=comparison[0]['candidate']
            exp=self.experiments.create(hypothesis,method,configuration={'candidate':selected,'comparison':comparison},dataset=dataset,code_version=code_version,model=model,project_id=project_id,research_id=research_project)
            self.experiments.observe(exp.experiment_id,{'research':obs.output,'verification':obs.verification})
        if not approved:return {'status':'WAITING_FOR_APPROVAL','experiment':exp.to_dict(),'comparison':comparison,'selected':selected}
        result=self.executor({'experiment_id':exp.experiment_id,'candidate':selected,'method':method,'dataset':dataset,'model':model})
        verification=result.get('verification',{}) if isinstance(result,dict) else {}
        if verification.get('verified') is not True:return {'status':'BLOCKED','experiment':exp.to_dict(),'reason':'execution_unverified'}
        self.experiments.record_result(exp.experiment_id,result.get('results',{}),result.get('metrics',{}))
        conclusion=str(result.get('conclusion') or 'Results recorded; no provider conclusion supplied.')
        self.experiments.conclude(exp.experiment_id,conclusion)
        document={'research_project':research_project,'selected_candidate':selected,'experiment_id':exp.experiment_id,'metrics':exp.metrics,'conclusion':exp.conclusion,'verification':verification}
        return {'status':'COMPLETE','experiment':exp.to_dict(),'comparison':comparison,'analysis':{'metrics':exp.metrics,'conclusion':exp.conclusion},'documentation':document}
