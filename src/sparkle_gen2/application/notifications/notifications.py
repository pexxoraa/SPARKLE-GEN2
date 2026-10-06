from __future__ import annotations
import hashlib,json,re,uuid
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime,timedelta
from typing import Any
from ...core_time import now

PRIORITIES=('LOW','NORMAL','HIGH','CRITICAL')
DECISIONS=frozenset({'DELIVER','AGGREGATE','SUPPRESS','ESCALATE'})
SECRET_KEYS=('secret','token','password','credential','api_key','authorization','private_key','access_token','refresh_token')

@dataclass(slots=True)
class Notification:
    notification_id:str;kind:str;title:str;body:str;priority:str;status:str;created_at:str
    owner_user_id:str='user';updated_at:str|None=None;decision:str='DELIVER';reason_code:str='LEGACY_DIRECT';why:str='Direct notification.';relevance:float=1.0;urgency:float=0.5;dedup_key:str|None=None;state_fingerprint:str|None=None;occurrence_count:int=1;provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

@dataclass(frozen=True,slots=True)
class NotificationCandidate:
    candidate_id:str;owner_user_id:str;event_type:str;subject:str;title:str;summary:str;relevance:float;urgency:float;priority:str;dedup_key:str;state_fingerprint:str;source_kind:str;source_id:str;created_at:str;correlation:dict[str,str]=field(default_factory=dict);provenance:dict[str,Any]=field(default_factory=dict);resolved:bool=False;stale:bool=False
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class NotificationDecision:
    decision_id:str;candidate_id:str;owner_user_id:str;decision:str;reason_code:str;why:str;created_at:str;notification_id:str|None=None;group_key:str|None=None;occurrence_count:int=1;provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

class NotificationCenter:
    def __init__(self,store=None):
        self.store=store;self.items={}
        if store is not None:
            for d in store.notifications():
                d=dict(d);d.setdefault('owner_user_id','user');d.setdefault('updated_at',None);d.setdefault('decision','DELIVER');d.setdefault('reason_code','LEGACY_DIRECT');d.setdefault('why','Direct notification.');d.setdefault('relevance',1.0);d.setdefault('urgency',.5);d.setdefault('dedup_key',None);d.setdefault('state_fingerprint',None);d.setdefault('occurrence_count',1);d.setdefault('provenance',{})
                self.items[d['notification_id']]=Notification(**d)
    def _save(self,n):
        self.items[n.notification_id]=n
        if self.store is not None:self.store.save_notification(n)
        return n
    def create(self,kind,title,body,priority='NORMAL',*,owner_user_id='user',decision='DELIVER',reason_code='LEGACY_DIRECT',why='Direct notification.',relevance=1.0,urgency=.5,dedup_key=None,state_fingerprint=None,occurrence_count=1,provenance=None):
        if priority not in PRIORITIES:raise ValueError('invalid priority')
        if decision not in DECISIONS:raise ValueError('invalid notification decision')
        if not isinstance(owner_user_id,str) or not owner_user_id.strip():raise ValueError('notification owner required')
        stamp=now();return self._save(Notification(uuid.uuid4().hex,str(kind)[:80],str(title)[:300],str(body)[:1000],priority,'UNREAD',stamp,owner_user_id,stamp,decision,str(reason_code)[:80],str(why)[:500],float(relevance),float(urgency),dedup_key,state_fingerprint,max(1,int(occurrence_count)),dict(provenance or {})))
    def read(self,nid,*,owner_user_id=None):
        n=self.items[nid]
        if owner_user_id is not None and n.owner_user_id!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        n.status='READ';n.updated_at=now();return self._save(n)
    def dismiss(self,nid,*,owner_user_id=None):
        n=self.items[nid]
        if owner_user_id is not None and n.owner_user_id!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        n.status='DISMISSED';n.updated_at=now();return self._save(n)
    def resolve(self,nid,*,owner_user_id=None):
        n=self.items[nid]
        if owner_user_id is not None and n.owner_user_id!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        n.status='RESOLVED';n.updated_at=now();return self._save(n)
    def list_unread(self,*,owner_user_id=None):return [n for n in self.items.values() if n.status=='UNREAD' and (owner_user_id is None or n.owner_user_id==owner_user_id)]

class NotificationIntelligenceService:
    """Deterministic owner-scoped attention layer over the existing NotificationCenter."""
    RELEVANCE_THRESHOLD=.45
    WINDOW_MINUTES=60
    MAX_DELIVERIES_PER_WINDOW=6
    MAX_LOW_NORMAL_PER_WINDOW=4
    ESCALATION_COOLDOWN_MINUTES=30
    HIGH_EVENT_TYPES=frozenset({'approval_waiting','deadline_approaching','automation_failure','background_failure','device_failure','robot_safety','critical_failure'})
    LOW_EVENT_TYPES=frozenset({'heartbeat','tool_observed','context_retrieved','goal_created','debug','telemetry'})
    RECOVERY_TYPES=frozenset({'recovered','connector_recovered','device_recovered','automation_recovered','background_recovered','robot_recovered'})
    def __init__(self,store,*,center=None,delivery=None):self.store=store;self.center=center or NotificationCenter(store);self.delivery=delivery
    @staticmethod
    def _clean(value,limit=1000):
        text=str(value)[:limit]
        patterns=[r'(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+',r'(?i)((?:api[_-]?key|token|password|secret|credential)\s*[:=]\s*)[^\s,;]+',r'(?i)\b(?:nvapi|sk|gh[pousr])-[A-Za-z0-9_-]{12,}\b',r'(?i)\bgh[pousr]_[A-Za-z0-9]{12,}\b']
        for pattern in patterns:text=re.sub(pattern,lambda m:(m.group(1)+'[REDACTED]') if m.lastindex else '[REDACTED]',text)
        return text
    @staticmethod
    def _safe_map(value):
        out={}
        for k,v in dict(value or {}).items():
            key=str(k);low=key.lower()
            if any(s in low for s in SECRET_KEYS) or key in {'raw','content','requested_scope','chain_of_thought'}:continue
            if isinstance(v,(str,int,float,bool)) or v is None:out[key]=NotificationIntelligenceService._clean(v,300) if isinstance(v,str) else v
        return out
    @staticmethod
    def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    @staticmethod
    def _priority(relevance,urgency,event_type,resolved=False):
        if resolved:return 'NORMAL'
        score=max(float(relevance),float(urgency))
        if event_type in {'robot_safety','critical_failure'} or score>=.95:return 'CRITICAL'
        if event_type in NotificationIntelligenceService.HIGH_EVENT_TYPES or score>=.78:return 'HIGH'
        if score>=.5:return 'NORMAL'
        return 'LOW'
    def candidate(self,*,owner_user_id,event_type,subject,title,summary,source_kind,source_id,state=None,relevance=None,urgency=None,correlation=None,provenance=None,resolved=False,stale=False):
        if not isinstance(owner_user_id,str) or not owner_user_id.strip():raise ValueError('notification owner required')
        if not all(isinstance(x,str) and x.strip() for x in (event_type,subject,title,source_kind,source_id)):raise ValueError('notification candidate identity fields required')
        rel=float(relevance if relevance is not None else self._default_relevance(event_type,state,resolved,stale));urg=float(urgency if urgency is not None else self._default_urgency(event_type,state,resolved,stale))
        if not 0<=rel<=1 or not 0<=urg<=1:raise ValueError('notification relevance/urgency out of range')
        canonical_state=self._safe_map(state or {});family=self._condition_family(event_type);dedup_key=self._hash({'owner':owner_user_id,'family':family,'subject':subject,'source_kind':source_kind})[:32];state_fp=self._hash({'state':canonical_state,'resolved':bool(resolved),'stale':bool(stale),'event_type':event_type})[:32];candidate_id=self._hash({'owner':owner_user_id,'source_kind':source_kind,'source_id':source_id,'event_type':event_type,'state':state_fp})[:32]
        return NotificationCandidate(candidate_id,owner_user_id,event_type,self._clean(subject,200),self._clean(title,300),self._clean(summary,1000),rel,urg,self._priority(rel,urg,event_type,resolved),dedup_key,state_fp,source_kind,self._clean(source_id,200),now(),self._safe_map(correlation),self._safe_map(provenance),bool(resolved),bool(stale))
    @staticmethod
    def _condition_family(event_type):
        e=event_type.lower()
        for suffix in ('_recovered','_resolved','_failure','_failed','_offline','_unavailable'):
            if e.endswith(suffix):return e[:-len(suffix)]
        return e
    def _default_relevance(self,event_type,state,resolved,stale):
        if event_type in self.LOW_EVENT_TYPES:return .1
        if resolved or event_type in self.RECOVERY_TYPES:return .72
        if event_type=='approval_waiting':return .96
        if event_type=='deadline_approaching':return .9
        if event_type in {'robot_safety','critical_failure'}:return 1.0
        if event_type in {'automation_failure','background_failure','device_failure'}:return .86
        if stale:return .55
        return .6
    def _default_urgency(self,event_type,state,resolved,stale):
        if resolved:return .5
        if event_type=='approval_waiting':return .9
        if event_type=='deadline_approaching':
            try:
                hours=float((state or {}).get('hours_remaining',72));return 1.0 if hours<=6 else .85 if hours<=24 else .6
            except (TypeError,ValueError):return .7
        if event_type in {'robot_safety','critical_failure'}:return 1.0
        if event_type in {'automation_failure','background_failure','device_failure'}:return .82
        if stale:return .45
        return .5
    def _decisions(self,owner):return self.store.notification_decisions(owner_user_id=owner)
    def _recent_deliveries(self,owner,at):
        cutoff=at-timedelta(minutes=self.WINDOW_MINUTES);out=[]
        for d in self._decisions(owner):
            if d.get('decision') not in {'DELIVER','ESCALATE'}:continue
            try:stamp=datetime.fromisoformat(str(d.get('created_at')).replace('Z','+00:00'));stamp=stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
            except Exception:continue
            if stamp>=cutoff:out.append(d)
        return out
    def _persist_decision(self,c,decision,reason,why,notification_id=None,occurrence_count=1):
        did=self._hash({'candidate_id':c.candidate_id,'decision':decision,'reason':reason})[:32];d=NotificationDecision(did,c.candidate_id,c.owner_user_id,decision,reason,self._clean(why,500),now(),notification_id,c.dedup_key,int(occurrence_count),{'source_kind':c.source_kind,'source_id':c.source_id,'correlation':c.correlation,'candidate':c.to_dict()});self.store.save_notification_decision(d);
        if self.delivery is not None:self.delivery.handle_decision(d)
        return d
    def evaluate(self,c:NotificationCandidate):
        existing=self.store.notification_decision_for_candidate(c.candidate_id)
        if existing is not None:return NotificationDecision(**existing)
        prior=[d for d in self._decisions(c.owner_user_id) if d.get('group_key')==c.dedup_key]
        latest=prior[-1] if prior else None
        if c.resolved or c.event_type in self.RECOVERY_TYPES:
            if not latest or not latest.get('notification_id'):
                return self._persist_decision(c,'SUPPRESS','RESOLVED_BEFORE_DELIVERY','The condition resolved before any user notification was delivered.')
            try:self.center.resolve(latest['notification_id'],owner_user_id=c.owner_user_id)
            except (KeyError,PermissionError):pass
            n=self.center.create(c.source_kind,c.title,c.summary,'NORMAL',owner_user_id=c.owner_user_id,decision='DELIVER',reason_code='RECOVERY_VERIFIED',why='A previously surfaced condition is verified recovered.',relevance=c.relevance,urgency=c.urgency,dedup_key=c.dedup_key,state_fingerprint=c.state_fingerprint,provenance={'candidate_id':c.candidate_id,'source_kind':c.source_kind,'source_id':c.source_id,'correlation':c.correlation})
            return self._persist_decision(c,'DELIVER','RECOVERY_VERIFIED','A previously surfaced condition is verified recovered.',n.notification_id)
        if c.relevance<self.RELEVANCE_THRESHOLD:return self._persist_decision(c,'SUPPRESS','BELOW_RELEVANCE_THRESHOLD',f'Relevance {c.relevance:.2f} is below the delivery threshold.')
        same_state=[d for d in prior if ((d.get('provenance') or {}).get('candidate') or {}).get('state_fingerprint')==c.state_fingerprint]
        if same_state:
            last=same_state[-1];nid=last.get('notification_id');count=int(last.get('occurrence_count',1))+1
            if nid:
                try:
                    n=self.center.items[nid];n.occurrence_count=max(n.occurrence_count+1,count);n.updated_at=now();n.decision='AGGREGATE';n.reason_code='EQUIVALENT_STATE_AGGREGATED';n.why=f'{n.occurrence_count} equivalent verified events were grouped to avoid repeated alerts.'
                    if n.occurrence_count>=2:n.body=self._clean(f'{n.occurrence_count} related events: {c.summary}',1000)
                    self.center._save(n)
                except KeyError:nid=None
            return self._persist_decision(c,'AGGREGATE','EQUIVALENT_STATE_AGGREGATED','Equivalent verified state was grouped with an existing notification.',nid,count)
        instant=datetime.now(UTC);recent=self._recent_deliveries(c.owner_user_id,instant);low_normal=sum(1 for d in recent if (((d.get('provenance') or {}).get('candidate') or {}).get('priority') in {'LOW','NORMAL'}))
        escalation=c.priority in {'HIGH','CRITICAL'} and c.event_type in self.HIGH_EVENT_TYPES
        if not escalation and (len(recent)>=self.MAX_DELIVERIES_PER_WINDOW or (c.priority in {'LOW','NORMAL'} and low_normal>=self.MAX_LOW_NORMAL_PER_WINDOW)):
            return self._persist_decision(c,'SUPPRESS','ATTENTION_BUDGET_EXHAUSTED',f'Owner attention budget for the last {self.WINDOW_MINUTES} minutes is exhausted.')
        if escalation and latest and latest.get('decision')=='ESCALATE' and latest.get('notification_id'):
            try:
                last_stamp=datetime.fromisoformat(str(latest.get('created_at')).replace('Z','+00:00'));last_stamp=last_stamp if last_stamp.tzinfo else last_stamp.replace(tzinfo=UTC)
                if instant-last_stamp<timedelta(minutes=self.ESCALATION_COOLDOWN_MINUTES):
                    n=self.center.items[latest['notification_id']];n.occurrence_count+=1;n.updated_at=now();n.decision='AGGREGATE';n.reason_code='ESCALATION_COOLDOWN_AGGREGATED';n.why='A recent escalation for the same condition is already visible; this update was grouped.';self.center._save(n)
                    return self._persist_decision(c,'AGGREGATE','ESCALATION_COOLDOWN_AGGREGATED','A recent escalation for the same condition is already visible; this update was grouped.',n.notification_id,n.occurrence_count)
            except (KeyError,ValueError,TypeError):pass
        decision='ESCALATE' if escalation else 'DELIVER';reason='HIGH_IMPORTANCE_UNRESOLVED' if escalation else ('STALE_EVIDENCE' if c.stale else 'RELEVANT_STATE_CHANGE')
        if c.event_type=='approval_waiting':why='An approval is waiting for your decision.'
        elif c.event_type=='deadline_approaching':why='A persisted deadline is approaching within the configured attention horizon.'
        elif c.stale:why='The latest verified observation is stale; the notification does not claim the state is current.'
        elif escalation:why='A high-importance verified condition requires attention.'
        else:why='A relevant verified state change passed the attention policy.'
        n=self.center.create(c.source_kind,c.title,c.summary,c.priority,owner_user_id=c.owner_user_id,decision=decision,reason_code=reason,why=why,relevance=c.relevance,urgency=c.urgency,dedup_key=c.dedup_key,state_fingerprint=c.state_fingerprint,provenance={'candidate_id':c.candidate_id,'source_kind':c.source_kind,'source_id':c.source_id,'correlation':c.correlation})
        return self._persist_decision(c,decision,reason,why,n.notification_id)
    def process(self,**kwargs):return self.evaluate(self.candidate(**kwargs))
    def create(self,kind,title,body,priority='NORMAL',*,owner_user_id='user',source_kind=None,source_id=None,event_type=None,state=None,correlation=None,provenance=None,resolved=False,stale=False,relevance=None,urgency=None):
        event_type=event_type or kind;source_kind=source_kind or kind;source_id=source_id or self._hash({'kind':kind,'title':title,'body':body,'state':self._safe_map(state or {})})[:24]
        c=self.candidate(owner_user_id=owner_user_id,event_type=event_type,subject=str((state or {}).get('subject') or title),title=title,summary=body,source_kind=source_kind,source_id=str(source_id),state=state,relevance=relevance,urgency=urgency,correlation=correlation,provenance=provenance,resolved=resolved,stale=stale)
        if priority in PRIORITIES and priority!='NORMAL':
            rank={p:i for i,p in enumerate(PRIORITIES)}
            if rank[priority]>rank[c.priority]:c=NotificationCandidate(**(c.to_dict()|{'priority':priority}))
        d=self.evaluate(c);return self.center.items.get(d.get('notification_id')) if isinstance(d,dict) else self.center.items.get(d.notification_id)
    def process_proactive(self,engine,event_id,*,owner_user_id='user'):
        e=engine.evaluate(event_id)
        if e.action!='NOTIFY' or e.status!='READY':
            c=self.candidate(owner_user_id=owner_user_id,event_type=e.event_type,subject=e.subject,title=e.subject,summary=e.rationale or 'No notification required.',source_kind='proactive_event',source_id=e.event_id,state=e.payload,relevance=e.relevance,urgency=e.relevance,provenance={'proactive_event_id':e.event_id})
            return self._persist_decision(c,'SUPPRESS','PROACTIVE_POLICY_NO_DELIVERY',e.rationale or 'Proactive policy did not authorize notification.')
        return self.process(owner_user_id=owner_user_id,event_type=e.event_type,subject=e.subject,title=e.subject,summary=e.rationale or f'{e.event_type} requires attention.',source_kind='proactive_event',source_id=e.event_id,state=e.payload,relevance=e.relevance,urgency=e.relevance,provenance={'proactive_event_id':e.event_id,'policy':self._safe_map(e.policy)})
    def inspect(self,notification_id,*,owner_user_id):
        n=self.center.items[notification_id]
        if n.owner_user_id!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        return n.to_dict()
    def explain(self,notification_id,*,owner_user_id):
        n=self.center.items[notification_id]
        if n.owner_user_id!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        return {'notification_id':n.notification_id,'decision':n.decision,'priority':n.priority,'reason_code':n.reason_code,'why':n.why,'occurrence_count':n.occurrence_count,'provenance':self._safe_map(n.provenance),'status':n.status}
    @property
    def items(self):return self.center.items
    def read(self,nid,*,owner_user_id=None):return self.center.read(nid,owner_user_id=owner_user_id)
    def dismiss(self,nid,*,owner_user_id=None):return self.center.dismiss(nid,owner_user_id=owner_user_id)
    def list_unread(self,*,owner_user_id=None):return self.center.list_unread(owner_user_id=owner_user_id)

    def attention(self,owner_user_id,*,limit=50):
        rows=[n.to_dict() for n in self.center.items.values() if n.owner_user_id==owner_user_id and n.status not in {'DISMISSED','RESOLVED'}]
        rows.sort(key=lambda x:(PRIORITIES.index(x.get('priority','NORMAL')),int(x.get('occurrence_count',1))),reverse=True);return rows[:max(1,min(int(limit),100))]
