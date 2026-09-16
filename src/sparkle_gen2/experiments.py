from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass,field
from .core_time import now

@dataclass(slots=True)
class Experiment:
    experiment_id:str; hypothesis:str; method:str; status:str; created_at:str
    configuration:dict=field(default_factory=dict);dataset:str|None=None;code_version:str|None=None;model:str|None=None
    project_id:str|None=None;research_id:str|None=None;observations:list[dict]=field(default_factory=list)
    results:dict=field(default_factory=dict);metrics:dict=field(default_factory=dict);conclusion:str|None=None
    def to_dict(self):return asdict(self)
class ExperimentManager:
    def __init__(self):self.items={}
    def create(self,hypothesis,method,*,configuration=None,dataset=None,code_version=None,model=None,project_id=None,research_id=None):
        if not hypothesis.strip() or not method.strip():raise ValueError('hypothesis and method required')
        e=Experiment(uuid.uuid4().hex,hypothesis,method,'PLANNED',now(),dict(configuration or {}),dataset,code_version,model,project_id,research_id);self.items[e.experiment_id]=e;return e
    def observe(self,eid,evidence):
        e=self.items[eid]
        if e.status in {'COMPLETED','CANCELLED'}:raise ValueError('experiment closed')
        e.status='RUNNING';e.observations.append(dict(evidence));return e
    def record_result(self,eid,results,metrics=None):
        e=self.items[eid]
        if e.status in {'COMPLETED','CANCELLED'}:raise ValueError('experiment closed')
        e.status='RUNNING';e.results=dict(results);e.metrics=dict(metrics or {});return e
    def conclude(self,eid,conclusion):
        e=self.items[eid]
        if not e.observations and not e.results:raise ValueError('evidence required')
        if not str(conclusion).strip():raise ValueError('conclusion required')
        e.conclusion=str(conclusion);e.status='COMPLETED';return e
