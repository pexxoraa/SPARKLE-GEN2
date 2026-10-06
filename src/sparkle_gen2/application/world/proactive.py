from __future__ import annotations
import hashlib,json,uuid
from dataclasses import asdict,dataclass,field
from ...core_time import now

MAX_EVENT_PAYLOAD_BYTES=32_000
MAX_PENDING_EVENTS=500
PRIORITIES=frozenset({'LOW','NORMAL','HIGH','CRITICAL'})

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
    fingerprint:str|None=None
    correlation_id:str|None=None
    priority:str='NORMAL'
    def to_dict(self):return asdict(self)

class ProactiveEventEngine:
    def __init__(self,store,*,threshold=0.7,relevance_fn=None,context_fn=None,decision_fn=None,policy_fn=None):
        if not 0<=threshold<=1:raise ValueError('threshold out of range')
        self.store=store;self.threshold=threshold;self.relevance_fn=relevance_fn;self.context_fn=context_fn;self.decision_fn=decision_fn;self.policy_fn=policy_fn
    @staticmethod
    def _bounded(event_type,subject,payload,correlation_id,priority):
        if not isinstance(event_type,str) or not event_type.strip() or len(event_type)>120:raise ValueError('event_type invalid')
        if not isinstance(subject,str) or not subject.strip() or len(subject)>500:raise ValueError('subject invalid')
        if not isinstance(payload,dict):raise ValueError('event payload must be an object')
        raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if len(raw)>MAX_EVENT_PAYLOAD_BYTES:raise ValueError('event payload too large')
        if correlation_id is not None and (not isinstance(correlation_id,str) or not correlation_id or len(correlation_id)>160):raise ValueError('correlation_id invalid')
        priority=str(priority).upper()
        if priority not in PRIORITIES:raise ValueError('priority invalid')
        fingerprint=hashlib.sha256(json.dumps({'event_type':event_type.strip(),'subject':subject.strip(),'payload':payload,'correlation_id':correlation_id},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        return event_type.strip(),subject.strip(),dict(payload),correlation_id,priority,fingerprint
    def ingest(self,event_type,subject,payload,relevance=None,*,correlation_id=None,priority='NORMAL'):
        event_type,subject,payload,correlation_id,priority,fingerprint=self._bounded(event_type,subject,payload,correlation_id,priority)
        existing=getattr(self.store,'proactive_events',lambda limit=1000:[])()
        duplicate=next((e for e in existing if getattr(e,'fingerprint',None)==fingerprint and e.status not in {'FAILED','CANCELLED'}),None)
        if duplicate is not None:return duplicate
        active=sum(1 for e in existing if e.status in {'PENDING','READY'})
        if active>=MAX_PENDING_EVENTS:raise RuntimeError('proactive_event_queue_limit_reached')
        if relevance is None:
            if self.relevance_fn is None:raise ValueError('relevance or relevance_fn required')
            relevance=float(self.relevance_fn(event_type,subject,dict(payload)))
        if not 0<=relevance<=1:raise ValueError('relevance out of range')
        status='IGNORED' if relevance<self.threshold else 'PENDING';e=ProactiveEvent(uuid.uuid4().hex,event_type,subject,payload,relevance,status,now(),fingerprint=fingerprint,correlation_id=correlation_id,priority=priority);self.store.save_proactive_event(e);return e
    def _default_decision(self,e,context):
        if e.event_type in {'deadline_approaching','automation_failure','device_failure','research_finished','important_email','meeting_approaching'}:return {'action':'NOTIFY','rationale':'relevant event type requires concise user notification'}
        return {'action':'NONE','rationale':'no approved proactive action for event type'}
    def evaluate(self,event_id):
        e=self.store.load_proactive_event(event_id)
        if e.status!='PENDING':return e
        e.context=dict(self.context_fn(e) if self.context_fn else {});decision=self.decision_fn(e,e.context) if self.decision_fn else self._default_decision(e,e.context);action=str(decision.get('action','NONE'));e.rationale=str(decision.get('rationale',''))[:500];policy=self.policy_fn(e,action,e.context) if self.policy_fn else {'allowed':action in {'NOTIFY','NONE'},'reason':'default notification-only proactive policy'};e.policy=dict(policy)
        if policy.get('allowed') is not True:e.action='NONE';e.status='BLOCKED'
        elif action=='NONE':e.action='NONE';e.status='IGNORED'
        else:e.action=action;e.status='READY'
        self.store.save_proactive_event(e);return e
