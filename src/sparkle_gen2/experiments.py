from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass,field
from .core_time import now

@dataclass(slots=True)
class Experiment:
    experiment_id:str
    hypothesis:str
    method:str
    status:str
    created_at:str
    observations:list[dict]=field(default_factory=list)
    conclusion:str|None=None
    def to_dict(self):return asdict(self)
class ExperimentManager:
    def __init__(self):self.items={}
    def create(self,hypothesis,method):
        if not hypothesis.strip() or not method.strip():raise ValueError('hypothesis and method required')
        e=Experiment(uuid.uuid4().hex,hypothesis,method,'PLANNED',now());self.items[e.experiment_id]=e;return e
    def observe(self,eid,evidence):
        e=self.items[eid]
        if e.status in {'COMPLETED','CANCELLED'}:raise ValueError('experiment closed')
        e.status='RUNNING';e.observations.append(dict(evidence));return e
    def conclude(self,eid,conclusion):
        e=self.items[eid]
        if not e.observations:raise ValueError('evidence required')
        e.conclusion=conclusion;e.status='COMPLETED';return e
