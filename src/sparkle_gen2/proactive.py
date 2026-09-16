from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass, field
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
    context:dict=field(default_factory=dict)
    rationale:str|None=None
    policy:dict=field(default_factory=dict)
    def to_dict(self): return asdict(self)

class ProactiveEventEngine:
    def __init__(self,store,*,threshold=0.7,relevance_fn=None,context_fn=None,decision_fn=None,policy_fn=None):
        if not 0<=threshold<=1:raise ValueError('threshold out of range')
        self.store=store;self.threshold=threshold;self.relevance_fn=relevance_fn;self.context_fn=context_fn;self.decision_fn=decision_fn;self.policy_fn=policy_fn
    def ingest(self,event_type,subject,payload,relevance=None):
        if relevance is None:
            if self.relevance_fn is None:raise ValueError('relevance or relevance_fn required')
            relevance=float(self.relevance_fn(event_type,subject,dict(payload)))
        if not 0<=relevance<=1: raise ValueError('relevance out of range')
        status='IGNORED' if relevance<self.threshold else 'PENDING'
        e=ProactiveEvent(uuid.uuid4().hex,event_type,subject,dict(payload),relevance,status,now());self.store.save_proactive_event(e);return e
    def _default_decision(self,e,context):
        if e.event_type in {'deadline_approaching','automation_failure','device_failure','research_finished','important_email','meeting_approaching'}:
            return {'action':'NOTIFY','rationale':'relevant event type requires concise user notification'}
        return {'action':'NONE','rationale':'no approved proactive action for event type'}
    def evaluate(self,event_id):
        e=self.store.load_proactive_event(event_id)
        if e.status!='PENDING':return e
        e.context=dict(self.context_fn(e) if self.context_fn else {})
        decision=self.decision_fn(e,e.context) if self.decision_fn else self._default_decision(e,e.context)
        action=str(decision.get('action','NONE'));e.rationale=str(decision.get('rationale',''))[:500]
        policy=self.policy_fn(e,action,e.context) if self.policy_fn else {'allowed':action in {'NOTIFY','NONE'},'reason':'default notification-only proactive policy'}
        e.policy=dict(policy)
        if policy.get('allowed') is not True:
            e.action='NONE';e.status='BLOCKED'
        elif action=='NONE':
            e.action='NONE';e.status='IGNORED'
        else:
            e.action=action;e.status='READY'
        self.store.save_proactive_event(e);return e
