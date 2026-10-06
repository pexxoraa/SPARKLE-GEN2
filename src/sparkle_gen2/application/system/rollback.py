from __future__ import annotations
import hashlib,json,uuid
from dataclasses import asdict,dataclass,field
from ...core_time import now

MAX_ROLLBACK_EVIDENCE_BYTES=32_000

@dataclass(slots=True)
class RollbackRecord:
    rollback_id:str
    goal_id:str
    action:str
    strategy:str
    status:str
    created_at:str
    evidence:dict=field(default_factory=dict)
    recovery_reference:str|None=None
    updated_at:str|None=None
    def to_dict(self):return asdict(self)

class RollbackManager:
    """Restart-safe rollback metadata. Trusted executors remain external to this manager."""
    def __init__(self,store=None):
        self.store=store
        self.records={r.rollback_id:r for r in store.rollback_records()} if store is not None else {}
    @staticmethod
    def _bounded_text(value,label,limit=500):
        value=str(value or '').strip()
        if not value or len(value)>limit:raise ValueError(f'{label} invalid')
        return value
    @staticmethod
    def _bounded_evidence(value):
        if not isinstance(value,dict):raise ValueError('rollback evidence must be an object')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if len(raw)>MAX_ROLLBACK_EVIDENCE_BYTES:raise ValueError('rollback evidence exceeds bound')
        return dict(value)
    def _save(self,record):
        record.updated_at=now()
        self.records[record.rollback_id]=record
        if self.store is not None:self.store.save_rollback_record(record)
        return record
    def prepare(self,goal_id,action,strategy,*,recovery_reference=None):
        goal_id=self._bounded_text(goal_id,'goal_id',160);action=self._bounded_text(action,'action',240);strategy=self._bounded_text(strategy,'rollback strategy',500)
        if strategy=='none':raise ValueError('rollback strategy required')
        ref=None if recovery_reference is None else self._bounded_text(recovery_reference,'recovery reference',500)
        stamp=now();r=RollbackRecord(uuid.uuid4().hex,goal_id,action,strategy,'READY',stamp,{},ref,stamp);return self._save(r)
    def inspect(self,rollback_id):
        if rollback_id not in self.records:raise KeyError(rollback_id)
        return self.records[rollback_id]
    def execute(self,rid,executor,*,approved=False):
        r=self.inspect(rid)
        if not approved:raise PermissionError('approval_required')
        if r.status=='VERIFIED':return r
        if r.status not in {'READY','FAILED'}:raise ValueError('rollback record is not executable')
        if not callable(executor):raise ValueError('trusted rollback executor required')
        r.status='EXECUTING';self._save(r)
        try:evidence=executor(r.strategy)
        except Exception as exc:
            r.evidence={'verified':False,'error_type':type(exc).__name__};r.status='FAILED';self._save(r);raise
        r.evidence=self._bounded_evidence(evidence if isinstance(evidence,dict) else {'result':evidence})
        r.status='VERIFIED' if r.evidence.get('verified') is True else 'FAILED';return self._save(r)
    def restart_reconcile(self):
        changed=[]
        for r in self.records.values():
            if r.status=='EXECUTING':
                r.status='FAILED';r.evidence={'verified':False,'reason':'process_restart_during_rollback'};self._save(r);changed.append(r.rollback_id)
        return changed
    def provenance(self,rid):
        r=self.inspect(rid);return {'rollback_id':r.rollback_id,'goal_id':r.goal_id,'action':r.action,'strategy_sha256':hashlib.sha256(r.strategy.encode()).hexdigest(),'recovery_reference':r.recovery_reference,'status':r.status,'created_at':r.created_at,'updated_at':r.updated_at,'verification':dict(r.evidence)}
