from __future__ import annotations
import json,uuid
from dataclasses import asdict,dataclass,field
from ...core_time import now

CLOSED_EXPERIMENT_STATES=frozenset({'COMPLETED','CANCELLED','ARCHIVED'})
MAX_CONFIGURATION_BYTES=64_000
MAX_RESULT_BYTES=256_000
MAX_OBSERVATIONS=256
MAX_COMPARE=20

@dataclass(slots=True)
class Experiment:
    experiment_id:str; hypothesis:str; method:str; status:str; created_at:str
    configuration:dict=field(default_factory=dict);dataset:str|None=None;code_version:str|None=None;model:str|None=None
    project_id:str|None=None;research_id:str|None=None;observations:list[dict]=field(default_factory=list)
    results:dict=field(default_factory=dict);metrics:dict=field(default_factory=dict);conclusion:str|None=None
    updated_at:str|None=None;version:int=1;provenance:dict=field(default_factory=dict);verification_state:str='PENDING'
    def to_dict(self):return asdict(self)

class ExperimentManager:
    def __init__(self,store=None):
        self.store=store;self.items={}
        if store is not None:self.items={d['experiment_id']:Experiment(**d) for d in store.experiments()}
    @staticmethod
    def _bounded_dict(value,limit,label):
        if not isinstance(value,dict):raise ValueError(f'{label} must be an object')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if len(raw)>limit:raise ValueError(f'{label} exceeds size bound')
        return dict(value)
    def _touch(self,e):e.updated_at=now();e.version=max(1,int(e.version))+1;return self._save(e)
    def _save(self,e):
        if self.store is not None:self.store.save_experiment(e)
        return e
    def create(self,hypothesis,method,*,configuration=None,dataset=None,code_version=None,model=None,project_id=None,research_id=None,provenance=None):
        if not isinstance(hypothesis,str) or not hypothesis.strip() or len(hypothesis)>4000 or not isinstance(method,str) or not method.strip() or len(method)>4000:raise ValueError('hypothesis and method required and bounded')
        config=self._bounded_dict(dict(configuration or {}),MAX_CONFIGURATION_BYTES,'configuration');stamp=now();e=Experiment(uuid.uuid4().hex,hypothesis.strip(),method.strip(),'PLANNED',stamp,config,dataset,code_version,model,project_id,research_id,updated_at=stamp,provenance=dict(provenance or {}));self.items[e.experiment_id]=e;return self._save(e)
    def configure(self,eid,*,configuration=None,dataset=None,code_version=None,model=None):
        e=self.items[eid]
        if e.status not in {'PLANNED','PAUSED'}:raise ValueError('experiment configuration is locked while active or closed')
        if configuration is not None:e.configuration=self._bounded_dict(configuration,MAX_CONFIGURATION_BYTES,'configuration')
        if dataset is not None:e.dataset=str(dataset)[:1000]
        if code_version is not None:e.code_version=str(code_version)[:256]
        if model is not None:e.model=str(model)[:512]
        return self._touch(e)
    def observe(self,eid,evidence):
        e=self.items[eid]
        if e.status in CLOSED_EXPERIMENT_STATES:raise ValueError('experiment closed')
        if len(e.observations)>=MAX_OBSERVATIONS:raise ValueError('experiment observation limit reached')
        e.status='RUNNING';e.observations.append(self._bounded_dict(dict(evidence),MAX_RESULT_BYTES,'observation'));return self._touch(e)
    def record_result(self,eid,results,metrics=None,*,verification=None):
        e=self.items[eid]
        if e.status in CLOSED_EXPERIMENT_STATES:raise ValueError('experiment closed')
        e.status='RUNNING';e.results=self._bounded_dict(results,MAX_RESULT_BYTES,'results');e.metrics=self._bounded_dict(dict(metrics or {}),MAX_RESULT_BYTES,'metrics')
        if verification is not None:e.verification_state='VERIFIED' if isinstance(verification,dict) and verification.get('verified') is True else 'FAILED'
        return self._touch(e)
    def run(self,eid,runner,*,approved=False,resource_limits=None):
        e=self.items[eid]
        if e.status in CLOSED_EXPERIMENT_STATES:raise ValueError('experiment closed')
        if not approved:raise PermissionError('experiment_run_approval_required')
        if not callable(runner):raise ValueError('trusted experiment runner required')
        limits={'time_seconds':300,'max_result_bytes':MAX_RESULT_BYTES,'max_observations':MAX_OBSERVATIONS}|dict(resource_limits or {})
        if not 0<float(limits.get('time_seconds',0))<=3600 or not 1<=int(limits.get('max_result_bytes',0))<=1_000_000 or not 1<=int(limits.get('max_observations',0))<=MAX_OBSERVATIONS:raise ValueError('experiment resource limits invalid')
        e.status='RUNNING';self._touch(e)
        out=runner(e.to_dict(),dict(limits))
        if not isinstance(out,dict):e.status='FAILED';e.verification_state='FAILED';self._touch(e);raise RuntimeError('experiment runner returned malformed result')
        verification=out.get('verification')
        if not isinstance(verification,dict) or verification.get('verified') is not True:e.status='FAILED';e.verification_state='FAILED';self._touch(e);raise RuntimeError('experiment verification failed')
        observations=list(out.get('observations') or [])
        if len(observations)>int(limits['max_observations']):raise ValueError('experiment runner returned too many observations')
        for obs in observations:
            if len(e.observations)>=MAX_OBSERVATIONS:raise ValueError('experiment observation limit reached')
            e.observations.append(self._bounded_dict(obs,MAX_RESULT_BYTES,'observation'))
        e.results=self._bounded_dict(dict(out.get('results') or {}),int(limits['max_result_bytes']),'results');e.metrics=self._bounded_dict(dict(out.get('metrics') or {}),int(limits['max_result_bytes']),'metrics');e.verification_state='VERIFIED';return self._touch(e)
    def pause(self,eid):
        e=self.items[eid]
        if e.status!='RUNNING':raise ValueError('only running experiments can pause')
        e.status='PAUSED';return self._touch(e)
    def resume(self,eid):
        e=self.items[eid]
        if e.status!='PAUSED':raise ValueError('only paused experiments can resume')
        e.status='RUNNING';return self._touch(e)
    def cancel(self,eid):
        e=self.items[eid]
        if e.status in CLOSED_EXPERIMENT_STATES:raise ValueError('experiment closed')
        e.status='CANCELLED';return self._touch(e)
    def analyze(self,eid):
        e=self.items[eid]
        if not e.observations and not e.results:raise ValueError('evidence required')
        numeric={k:float(v) for k,v in e.metrics.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
        return {'experiment_id':eid,'status':e.status,'version':e.version,'verification_state':e.verification_state,'observation_count':len(e.observations),'metric_count':len(e.metrics),'numeric_metrics':numeric,'has_results':bool(e.results)}
    def compare(self,eids):
        ids=list(eids)
        if not 2<=len(ids)<=MAX_COMPARE or len(set(ids))!=len(ids):raise ValueError('compare requires 2..20 unique experiments')
        analyses=[self.analyze(x) for x in ids];common=set.intersection(*(set(a['numeric_metrics']) for a in analyses)) if analyses else set();comparison={}
        for key in sorted(common):comparison[key]=sorted(({'experiment_id':a['experiment_id'],'value':a['numeric_metrics'][key]} for a in analyses),key=lambda x:(-x['value'],x['experiment_id']))
        return {'experiments':analyses,'common_numeric_metrics':comparison}
    def conclude(self,eid,conclusion):
        e=self.items[eid]
        if not e.observations and not e.results:raise ValueError('evidence required')
        if not str(conclusion).strip():raise ValueError('conclusion required')
        e.conclusion=str(conclusion)[:8000];e.status='COMPLETED';return self._touch(e)
    def archive(self,eid):
        e=self.items[eid]
        if e.status not in {'COMPLETED','CANCELLED'}:raise ValueError('only completed or cancelled experiments can archive')
        e.status='ARCHIVED';return self._touch(e)
