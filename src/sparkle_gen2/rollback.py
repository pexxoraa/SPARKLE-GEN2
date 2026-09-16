from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass
from .core_time import now

@dataclass(slots=True)
class RollbackRecord:
    rollback_id:str
    goal_id:str
    action:str
    strategy:str
    status:str
    created_at:str
    evidence:dict
    def to_dict(self):return asdict(self)
class RollbackManager:
    def __init__(self):self.records={}
    def prepare(self,goal_id,action,strategy):
        if not strategy or strategy=='none':raise ValueError('rollback strategy required')
        r=RollbackRecord(uuid.uuid4().hex,goal_id,action,strategy,'READY',now(),{});self.records[r.rollback_id]=r;return r
    def execute(self,rid,executor,*,approved=False):
        r=self.records[rid]
        if not approved:raise PermissionError('approval_required')
        evidence=executor(r.strategy);r.evidence=evidence if isinstance(evidence,dict) else {'result':evidence};r.status='VERIFIED' if r.evidence.get('verified') else 'FAILED';return r
