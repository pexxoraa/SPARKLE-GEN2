from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass
from .core_time import now

@dataclass(slots=True)
class ProactiveEvent:
    event_id:str
    event_type:str
    subject:str
    payload:dict
    relevance:float
    status:str
    created_at:str
    action:str|None=None
    def to_dict(self): return asdict(self)

class ProactiveEventEngine:
    def __init__(self,store,*,threshold=0.7): self.store=store;self.threshold=threshold
    def ingest(self,event_type,subject,payload,relevance):
        if not 0<=relevance<=1: raise ValueError('relevance out of range')
        status='IGNORED' if relevance<self.threshold else 'PENDING'
        e=ProactiveEvent(uuid.uuid4().hex,event_type,subject,dict(payload),relevance,status,now());self.store.save_proactive_event(e);return e
    def evaluate(self,event_id):
        e=self.store.load_proactive_event(event_id)
        if e.status!='PENDING':return e
        if e.event_type in {'deadline_approaching','automation_failure','device_failure','research_finished'}:
            e.action='NOTIFY';e.status='READY'
        else:
            e.action='NONE';e.status='IGNORED'
        self.store.save_proactive_event(e);return e
