from __future__ import annotations
import hashlib,re,uuid
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime,timedelta
from typing import Any
from .core_time import now

CHANNELS=frozenset({'dashboard','desktop','voice','mobile'})
PERMISSIONS=frozenset({'GRANTED','DENIED','UNKNOWN','NOT_APPLICABLE'})
AVAILABILITY=frozenset({'AVAILABLE','UNAVAILABLE','PERMISSION_UNKNOWN','PERMISSION_DENIED'})
DELIVERY_STATUSES=frozenset({'PENDING','ACCEPTED','FAILED','UNAVAILABLE','ACKNOWLEDGED','EXPIRED'})
SENSITIVE_CLASSIFICATIONS=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})

@dataclass(slots=True)
class NotificationChannelState:
    channel_state_id:str;owner_user_id:str;channel:str;availability:str;permission:str;configured:bool;updated_at:str
    device_id:str|None=None;reason:str|None=None;provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class NotificationDeliveryAttempt:
    attempt_id:str;decision_id:str;notification_id:str;owner_user_id:str;channel:str;status:str;created_at:str;updated_at:str
    target_device_id:str|None=None;channel_reference:str|None=None;acknowledgement_status:str='UNACKNOWLEDGED';acknowledged_at:str|None=None;error:str|None=None;retry_count:int=0;parent_attempt_id:str|None=None;payload:dict[str,Any]=field(default_factory=dict);provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

class DeliveryPolicy:
    """Deterministic channel selection. It never changes the upstream notification decision."""
    def __init__(self,store):self.store=store
    def owner_policy(self,owner):
        base={'desktop_enabled':True,'quiet_hours':{'enabled':False,'start':'22:00','end':'07:00'}}
        value=self.store.load_setting(f'notification_delivery_policy:{owner}',{}) or {}
        if isinstance(value,dict):
            if isinstance(value.get('desktop_enabled'),bool):base['desktop_enabled']=value['desktop_enabled']
            q=value.get('quiet_hours')
            if isinstance(q,dict) and isinstance(q.get('enabled'),bool):base['quiet_hours']=base['quiet_hours']|{k:q[k] for k in ('enabled','start','end') if k in q}
        return base
    @staticmethod
    def _in_quiet_hours(policy,stamp=None):
        q=policy.get('quiet_hours') or {}
        if not q.get('enabled'):return False
        try:
            at=(stamp or datetime.now(UTC)).time();sh,sm=map(int,str(q.get('start','22:00')).split(':'));eh,em=map(int,str(q.get('end','07:00')).split(':'));start=at.replace(hour=sh,minute=sm,second=0,microsecond=0);end=at.replace(hour=eh,minute=em,second=0,microsecond=0)
            return at>=start or at<end if start>end else start<=at<end
        except Exception:return False
    def select(self,notification,decision,channel_states):
        if decision.get('decision')=='SUPPRESS' or not decision.get('notification_id'):return []
        priority=str(notification.get('priority','NORMAL'));selected=[{'channel':'dashboard','reason':'authoritative Personal Operations notification surface'}]
        if decision.get('decision')=='AGGREGATE' or priority=='LOW':return selected
        policy=self.owner_policy(notification.get('owner_user_id','user'));desktop=next((x for x in channel_states if x.get('channel')=='desktop' and x.get('availability')=='AVAILABLE'),None)
        quiet=self._in_quiet_hours(policy)
        if policy.get('desktop_enabled') and desktop is not None and (priority in {'HIGH','CRITICAL'} or not quiet):selected.append({'channel':'desktop','target_device_id':desktop.get('device_id'),'reason':'priority allows desktop and an authorized browser reports granted permission'})
        elif priority in {'NORMAL','HIGH','CRITICAL'}:
            reason='desktop disabled by owner policy' if not policy.get('desktop_enabled') else ('quiet hours suppress non-high desktop delivery' if quiet and priority=='NORMAL' else 'desktop channel is not currently available')
            selected.append({'channel':'desktop','unavailable':True,'reason':reason})
        return selected

class NotificationDeliveryOrchestrator:
    """Durable delivery projection over persisted NotificationDecision/Notification records."""
    PENDING_TTL_MINUTES=15
    def __init__(self,store):self.store=store;self.policy=DeliveryPolicy(store)
    @staticmethod
    def _id(*parts):return hashlib.sha256('|'.join(str(x) for x in parts).encode()).hexdigest()[:32]
    @staticmethod
    def _clean(text,limit):
        value=str(text or '')[:limit]
        pats=[r'(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+',r'(?i)((?:api[_-]?key|token|password|secret|credential)\s*[:=]\s*)[^\s,;]+',r'(?i)\b(?:nvapi|sk|gh[pousr])[-_][A-Za-z0-9_-]{12,}\b']
        for p in pats:value=re.sub(p,lambda m:(m.group(1)+'[REDACTED]') if m.lastindex else '[REDACTED]',value)
        return value
    def _notification(self,nid):
        row=next((x for x in self.store.notifications() if x.get('notification_id')==nid),None)
        if row is None:raise KeyError(nid)
        return row
    def register_channel(self,*,owner_user_id,channel,device_id=None,permission='UNKNOWN',supported=False,configured=False,provenance=None):
        if channel not in CHANNELS:raise ValueError('invalid_notification_channel')
        permission=str(permission).upper();
        if permission not in PERMISSIONS:raise ValueError('invalid_notification_permission')
        if channel=='dashboard':availability='AVAILABLE';permission='NOT_APPLICABLE';configured=True;reason='authoritative Personal Operations surface'
        elif channel in {'voice','mobile'}:availability='UNAVAILABLE';configured=False;permission='UNKNOWN';reason=f'{channel} delivery is not configured'
        elif not supported:availability='UNAVAILABLE';reason='no authorized browser has reported notification capability' if device_id is None else 'browser notification API unavailable'
        elif permission=='GRANTED':availability='AVAILABLE';configured=True;reason='authorized browser reports granted notification permission'
        elif permission=='DENIED':availability='PERMISSION_DENIED';reason='browser notification permission denied'
        else:availability='PERMISSION_UNKNOWN';reason='browser notification permission has not been granted'
        cid=self._id(owner_user_id,channel,device_id or 'none');row=NotificationChannelState(cid,owner_user_id,channel,availability,permission,bool(configured),now(),device_id,reason,dict(provenance or {}));self.store.save_notification_channel_state(row);return row
    def channel_states(self,owner_user_id):
        rows=self.store.notification_channel_states(owner_user_id=owner_user_id);by={(x['channel'],x.get('device_id')):x for x in rows}
        if not any(x['channel']=='dashboard' for x in rows):self.register_channel(owner_user_id=owner_user_id,channel='dashboard')
        if not any(x['channel']=='desktop' for x in rows):self.register_channel(owner_user_id=owner_user_id,channel='desktop',permission='UNKNOWN',supported=False,configured=False)
        for channel in ('voice','mobile'):
            if not any(x['channel']==channel for x in rows):self.register_channel(owner_user_id=owner_user_id,channel=channel)
        rows=self.store.notification_channel_states(owner_user_id=owner_user_id)
        devices={x.get('device_id'):x for x in self.store.device_identities()}
        for row in rows:
            if row.get('channel')=='desktop' and row.get('device_id'):
                dev=devices.get(row['device_id'])
                if dev is None or dev.get('revoked_at') or dev.get('status')=='REVOKED':row['availability']='UNAVAILABLE';row['reason']='authorized browser device is no longer available'
        rows.sort(key=lambda x:(x['channel'],x.get('device_id') or ''));return rows
    def _delivery_payload(self,notification):
        prov=notification.get('provenance') or {};classification=str(prov.get('classification') or prov.get('privacy_classification') or '').upper();protected=classification in SENSITIVE_CLASSIFICATIONS or bool(prov.get('sensitive'))
        if protected:return {'title':'SPARKLE notification','body':'Open SPARKLE to view protected notification.','notification_id':notification['notification_id'],'protected':True}
        return {'title':self._clean(notification.get('title'),180),'body':self._clean(notification.get('body'),280),'notification_id':notification['notification_id'],'protected':False}
    def _create_attempt(self,decision,notification,selection,*,retry_count=0,parent=None):
        channel=selection['channel'];target=selection.get('target_device_id');aid=self._id(decision['decision_id'],channel,target or 'none',retry_count);existing=self.store.notification_delivery_attempt(aid)
        if existing is not None:return NotificationDeliveryAttempt(**existing)
        if selection.get('unavailable'):status='UNAVAILABLE';error=selection.get('reason')
        elif channel=='dashboard':status='ACCEPTED';error=None
        else:status='PENDING';error=None
        stamp=now();attempt=NotificationDeliveryAttempt(aid,decision['decision_id'],notification['notification_id'],notification['owner_user_id'],channel,status,stamp,stamp,target,(f'dashboard:{notification["notification_id"]}' if channel=='dashboard' else None),'UNACKNOWLEDGED',None,error,retry_count,parent,self._delivery_payload(notification),{'selection_reason':selection.get('reason'),'decision':decision.get('decision'),'reason_code':decision.get('reason_code')});self.store.save_notification_delivery_attempt(attempt);return attempt
    def handle_decision(self,decision):
        d=decision.to_dict() if hasattr(decision,'to_dict') else dict(decision)
        if d.get('decision')=='SUPPRESS' or not d.get('notification_id'):return []
        notification=self._notification(d['notification_id']);states=self.channel_states(notification['owner_user_id']);return [self._create_attempt(d,notification,s) for s in self.policy.select(notification,d,states)]
    def attempts(self,owner_user_id,*,notification_id=None,decision_id=None):
        self.expire_stale(owner_user_id)
        return self.store.notification_delivery_attempts(owner_user_id=owner_user_id,notification_id=notification_id,decision_id=decision_id)
    def pending(self,owner_user_id,*,channel,device_id):
        if channel!='desktop':return []
        self.expire_stale(owner_user_id)
        return [x for x in self.store.notification_delivery_attempts(owner_user_id=owner_user_id,channel='desktop') if x.get('status')=='PENDING' and x.get('target_device_id')==device_id]
    def record_result(self,attempt_id,*,owner_user_id,device_id,status,channel_reference=None,error=None):
        row=self.store.notification_delivery_attempt(attempt_id)
        if row is None:raise KeyError(attempt_id)
        if row['owner_user_id']!=owner_user_id:raise PermissionError('notification_delivery_owner_mismatch')
        if row.get('target_device_id') and row.get('target_device_id')!=device_id:raise PermissionError('notification_delivery_device_mismatch')
        status=str(status).upper()
        if status not in {'ACCEPTED','FAILED'}:raise ValueError('invalid_channel_delivery_result')
        if row['status'] not in {'PENDING','FAILED'}:return row
        row['status']=status;row['updated_at']=now();row['channel_reference']=self._clean(channel_reference,200) if channel_reference else row.get('channel_reference');row['error']=self._clean(error,300) if error else None;self.store.save_notification_delivery_attempt(row);return row
    def acknowledge(self,attempt_id,*,owner_user_id,device_id=None):
        row=self.store.notification_delivery_attempt(attempt_id)
        if row is None:raise KeyError(attempt_id)
        if row['owner_user_id']!=owner_user_id:raise PermissionError('notification_delivery_owner_mismatch')
        if device_id is not None and row.get('target_device_id') and row['target_device_id']!=device_id:raise PermissionError('notification_delivery_device_mismatch')
        if row['status'] not in {'ACCEPTED','ACKNOWLEDGED'}:raise ValueError('delivery_not_accepted')
        row['status']='ACKNOWLEDGED';row['acknowledgement_status']='ACKNOWLEDGED';row['acknowledged_at']=row.get('acknowledged_at') or now();row['updated_at']=now();self.store.save_notification_delivery_attempt(row);return row
    def acknowledge_notification(self,notification_id,*,owner_user_id,channel='dashboard'):
        rows=[x for x in self.attempts(owner_user_id,notification_id=notification_id) if x.get('channel')==channel and x.get('status') in {'ACCEPTED','ACKNOWLEDGED'}]
        return [self.acknowledge(x['attempt_id'],owner_user_id=owner_user_id) for x in rows]
    def retry(self,attempt_id,*,owner_user_id):
        row=self.store.notification_delivery_attempt(attempt_id)
        if row is None:raise KeyError(attempt_id)
        if row['owner_user_id']!=owner_user_id:raise PermissionError('notification_delivery_owner_mismatch')
        siblings=self.store.notification_delivery_attempts(owner_user_id=owner_user_id,decision_id=row['decision_id'])
        active=[x for x in siblings if x.get('channel')==row['channel'] and x.get('target_device_id')==row.get('target_device_id') and x.get('status') in {'PENDING','ACCEPTED','ACKNOWLEDGED'}]
        if active:return active[-1]
        if row['status'] not in {'FAILED','UNAVAILABLE','EXPIRED'}:raise ValueError('delivery_not_retryable')
        if row['channel']=='desktop':
            state=next((x for x in self.channel_states(owner_user_id) if x.get('channel')=='desktop' and x.get('device_id')==row.get('target_device_id')),None)
            if not state or state.get('availability')!='AVAILABLE':raise RuntimeError('desktop_channel_unavailable')
        decision=next((x for x in self.store.notification_decisions(owner_user_id=owner_user_id) if x.get('decision_id')==row['decision_id']),None)
        if decision is None:raise KeyError(row['decision_id'])
        notification=self._notification(row['notification_id']);n=max([int(x.get('retry_count',0)) for x in siblings]+[0])+1;selection={'channel':row['channel'],'target_device_id':row.get('target_device_id'),'reason':'explicit bounded delivery retry'};return self._create_attempt(decision,notification,selection,retry_count=n,parent=row['attempt_id']).to_dict()
    def inspect(self,*,owner_user_id,notification_id=None,attempt_id=None):
        if attempt_id:
            row=self.store.notification_delivery_attempt(attempt_id)
            if row is None:raise KeyError(attempt_id)
            if row['owner_user_id']!=owner_user_id:raise PermissionError('notification_delivery_owner_mismatch')
            return {'attempt':row,'channels':self.channel_states(owner_user_id)}
        if not notification_id:raise ValueError('notification_id_or_attempt_id_required')
        n=self._notification(notification_id)
        if n['owner_user_id']!=owner_user_id:raise PermissionError('notification_owner_mismatch')
        return {'notification_id':notification_id,'attempts':self.attempts(owner_user_id,notification_id=notification_id),'channels':self.channel_states(owner_user_id)}
    def recover_all(self):
        owners=set()
        for decision in self.store.notification_decisions():
            owners.add(decision.get('owner_user_id','user'))
            if decision.get('notification_id') and decision.get('decision')!='SUPPRESS':self.handle_decision(decision)
        for owner in owners:self.expire_stale(owner)
        return {'owners':len(owners),'attempts':len(self.store.notification_delivery_attempts())}

    def expire_stale(self,owner_user_id):
        cutoff=datetime.now(UTC)-timedelta(minutes=self.PENDING_TTL_MINUTES)
        for row in self.store.notification_delivery_attempts(owner_user_id=owner_user_id):
            if row.get('status')!='PENDING':continue
            try:stamp=datetime.fromisoformat(str(row['created_at']).replace('Z','+00:00'));stamp=stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
            except Exception:stamp=cutoff-timedelta(seconds=1)
            if stamp<cutoff:row['status']='EXPIRED';row['updated_at']=now();row['error']='delivery attempt expired before channel acknowledgement';self.store.save_notification_delivery_attempt(row)
