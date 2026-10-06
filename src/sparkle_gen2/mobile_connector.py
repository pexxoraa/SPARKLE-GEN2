from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any

READ_ACTIONS=frozenset({'status','device_info','connection_status','capabilities'})
CONTROL_ACTIONS=frozenset({'request_notification','request_sync'})
MAX_CAPABILITIES=64
MAX_TEXT=240

class MobileConnectorError(RuntimeError):
    def __init__(self,category:str,message:str):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class MobileDeviceSummary:
    device_reference:str;kind:str;os_name:str;status:str;capabilities:tuple[str,...]
    def to_dict(self):return asdict(self)

class MobileDeviceAdapter:
    """Bounded connector over an already-authenticated mobile device transport.

    Enrollment/authentication remains authoritative in DeviceIdentityService. This adapter never
    receives or persists raw device tokens and cannot enroll/revoke/expand permissions.
    """
    provider='SPARKLE authenticated mobile-device transport'
    def __init__(self,*,owner_user_id='user',device_record=None,target=None):
        self.owner_user_id=owner_user_id;self.device_record=dict(device_record or {});self.target=target;self._closed=False
    @property
    def bound_device_id(self):return self.device_record.get('device_id') if self.configured() else None
    def configured(self):
        d=self.device_record
        return bool(self.target is not None and d.get('device_id') and str(d.get('kind','')).lower() in {'mobile','phone','tablet','android','ios'} and d.get('status')=='ONLINE' and not d.get('revoked_at'))
    @staticmethod
    def _hash(value):return hashlib.sha256(str(value).encode()).hexdigest()[:24]
    def _device_reference(self):
        did=self.device_record.get('device_id')
        return None if not did else 'mobile-device:'+self._hash(did)
    def authorize(self):
        if not self.configured():raise MobileConnectorError('AUTH_REQUIRED','authenticated mobile device transport is unavailable')
        return {'authorization_reference':'mobile-auth:'+self._hash(self.device_record['device_id']),'granted_scopes':['mobile.read','mobile.act'],'device_id':self.device_record['device_id']}
    def health(self):
        if self._closed:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REVOKED','provider':self.provider,'error_category':'REVOKED'}
        if not self.configured():return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REQUIRED','provider':self.provider,'error_category':'MOBILE_TARGET_UNAVAILABLE','device_reference':self._device_reference()}
        fn=getattr(self.target,'status',None)
        try:detail=fn() if callable(fn) else {'connected':True}
        except Exception:return {'ok':False,'status':'DEGRADED','authorization_state':'AUTHORIZED','provider':self.provider,'error_category':'MOBILE_TRANSPORT_UNAVAILABLE','device_reference':self._device_reference()}
        connected=bool(detail.get('connected',detail.get('status') in {'CONNECTED','ONLINE','AVAILABLE'})) if isinstance(detail,dict) else False
        return {'ok':connected,'status':'HEALTHY' if connected else 'DEGRADED','authorization_state':'AUTHORIZED','provider':self.provider,'device_reference':self._device_reference(),'transport_connected':connected}
    def _bind(self,owner_user_id,device_id):
        if self._closed:raise PermissionError('mobile_connector_revoked')
        if owner_user_id!=self.owner_user_id:raise PermissionError('mobile_owner_mismatch')
        if not self.configured():raise MobileConnectorError('AUTH_REQUIRED','authenticated mobile target unavailable')
        if device_id!=self.device_record.get('device_id'):raise PermissionError('mobile_device_mismatch')
    def _summary(self):
        caps=tuple(sorted(set(str(x)[:80] for x in (self.device_record.get('capabilities') or []) if isinstance(x,str)))[:MAX_CAPABILITIES])
        return MobileDeviceSummary(self._device_reference(),str(self.device_record.get('kind','mobile'))[:40],str(self.device_record.get('os_name','unknown'))[:80],str(self.device_record.get('status','UNKNOWN'))[:24],caps)
    def _read(self,payload):
        if set(payload)-{'action'}:raise ValueError('unsupported mobile.read argument')
        action=str(payload.get('action','status'))
        if action not in READ_ACTIONS:raise PermissionError('mobile_read_action_not_allowlisted')
        h=self.health();summary=self._summary()
        if action=='status':return {'action':action,'status':'CONNECTED' if h.get('ok') else 'UNAVAILABLE','device_reference':summary.device_reference}
        if action=='device_info':return {'action':action,'device':summary.to_dict()}
        if action=='connection_status':return {'action':action,'connected':bool(h.get('transport_connected')),'device_reference':summary.device_reference}
        return {'action':action,'capabilities':list(summary.capabilities),'device_reference':summary.device_reference}
    @staticmethod
    def _clean_text(value,limit=MAX_TEXT):
        if value is None:return None
        if not isinstance(value,str):raise ValueError('mobile text field must be string')
        value=value.strip()
        if len(value)>limit:raise ValueError('mobile text field exceeds bound')
        return value
    def _act(self,payload):
        allowed={'action','notification_id','sync_scope','cursor'}
        if set(payload)-allowed:raise ValueError('unsupported mobile.act argument')
        action=str(payload.get('action',''))
        if action not in CONTROL_ACTIONS:raise PermissionError('mobile_control_action_not_allowlisted')
        if action=='request_notification':
            nid=self._clean_text(payload.get('notification_id'),128)
            if not nid:raise ValueError('notification_id_required')
            fn=getattr(self.target,'request_notification',None)
            if not callable(fn):raise MobileConnectorError('UNSUPPORTED','mobile notification transport unavailable')
            result=fn({'notification_id':nid})
        else:
            scope=self._clean_text(payload.get('sync_scope'),80) or 'state';cursor=self._clean_text(payload.get('cursor'),160)
            if scope not in {'state','notifications','sessions','task_status'}:raise PermissionError('mobile_sync_scope_not_allowlisted')
            fn=getattr(self.target,'request_sync',None)
            if not callable(fn):raise MobileConnectorError('UNSUPPORTED','mobile sync transport unavailable')
            result=fn({'scope':scope,**({'cursor':cursor} if cursor else {})})
        if not isinstance(result,dict):raise MobileConnectorError('MALFORMED_RESPONSE','mobile target returned malformed result')
        return {'action':action,'accepted':bool(result.get('accepted')),'request_reference':str(result.get('request_reference') or '')[:160]}
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,device_id=None,**_context):
        self._bind(owner_user_id,device_id);p=dict(payload or {})
        if operation=='read':value=self._read(p)
        elif operation=='act':value=self._act(p)
        else:raise KeyError(operation)
        return {'provider':self.provider,'operation':operation,'device_reference':self._device_reference(),'result':value,'provider_reference':value.get('request_reference') or self._device_reference()}
    def invoke(self,operation,payload):return self.invoke_with_context(operation,payload,owner_user_id=self.owner_user_id,device_id=self.bound_device_id)
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:return {'verified':False,'reason':'mobile_owner_mismatch','method':'authenticated mobile target reread'}
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation:return {'verified':False,'reason':'provider_or_operation_mismatch','method':'authenticated mobile target reread'}
        try:
            health=self.health()
            if not health.get('ok'):return {'verified':False,'reason':'mobile_transport_unhealthy','method':'authenticated mobile target reread'}
            value=result.get('result') or {}
            if operation=='read':
                return {'verified':value.get('action') in READ_ACTIONS and result.get('device_reference')==self._device_reference(),'method':'device binding + transport health reread','device_reference':self._device_reference()}
            verifier=getattr(self.target,'verify',None)
            if not callable(verifier):return {'verified':False,'reason':'mobile_target_verifier_unavailable','method':'authenticated mobile target reread'}
            evidence=verifier(value.get('action'),dict(value))
            if not isinstance(evidence,dict) or evidence.get('verified') is not True:return {'verified':False,'reason':'mobile_target_verification_failed','method':'authenticated mobile target reread'}
            return {'verified':True,'method':str(evidence.get('method') or 'authenticated mobile target reread'),'device_reference':self._device_reference(),'verification_digest':hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        except Exception:return {'verified':False,'reason':'mobile_verification_failed','method':'authenticated mobile target reread'}
    def verify(self,operation,result):return self.verify_with_context(operation,result,owner_user_id=self.owner_user_id)
    def close(self):self._closed=True;return {'status':'closed','device_reference':self._device_reference()}
