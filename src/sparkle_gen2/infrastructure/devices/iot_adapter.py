from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass

READ_OPS=frozenset({'discover','read_state','read'})
CONTROL_OPS=frozenset({'control','act'})
MAX_STATE_BYTES=64_000
MAX_CONTROL_BYTES=16_000

class IoTAdapterError(RuntimeError):
    def __init__(self,category,message):super().__init__(message);self.category=category

@dataclass(frozen=True,slots=True)
class IoTObservation:
    device_reference:str;device_type:str;status:str;capabilities:tuple[str,...];state:dict
    def to_dict(self):return asdict(self)

class TypedIoTAdapter:
    """Bounded adapter over an already-authenticated device transport; never raw GPIO."""
    def __init__(self,device_record,transport,*,owner_user_id='user',scope_prefix='iot'):
        self.device=dict(device_record or {});self.transport=transport;self.owner_user_id=owner_user_id;self.scope_prefix=str(scope_prefix);self._closed=False
        if self.scope_prefix not in {'iot','esp32'}:raise ValueError('unsupported IoT scope prefix')
    @property
    def bound_device_id(self):return self.device.get('device_id') if self.configured() else None
    @staticmethod
    def _digest(v):return hashlib.sha256(str(v).encode()).hexdigest()[:24]
    def _reference(self):return None if not self.device.get('device_id') else 'iot-device:'+self._digest(self.device['device_id'])
    def configured(self):return bool(self.transport is not None and self.device.get('device_id') and self.device.get('status') not in {'REVOKED','OFFLINE'} and not self.device.get('revoked_at'))
    def authorize(self):
        if not self.configured():raise IoTAdapterError('AUTH_REQUIRED','authenticated IoT transport unavailable')
        scopes=['iot.discover','iot.read_state','iot.control'] if self.scope_prefix=='iot' else ['esp32.read','esp32.act']
        return {'authorization_reference':self.scope_prefix+'-auth:'+self._digest(self.device['device_id']),'device_id':self.device['device_id'],'granted_scopes':scopes}
    def health(self):
        if self._closed:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REVOKED','device_reference':self._reference()}
        if not self.configured():return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REQUIRED','device_reference':self._reference()}
        try:h=self.transport.health()
        except Exception:return {'ok':False,'status':'DEGRADED','authorization_state':'AUTHORIZED','device_reference':self._reference()}
        ok=isinstance(h,dict) and bool(h.get('ok',h.get('status') in {'CONNECTED','HEALTHY','AVAILABLE'}));return {'ok':ok,'status':'HEALTHY' if ok else 'DEGRADED','authorization_state':'AUTHORIZED','device_reference':self._reference()}
    def _bind(self,owner,device_id):
        if self._closed:raise PermissionError('iot_adapter_revoked')
        if owner!=self.owner_user_id:raise PermissionError('iot_owner_mismatch')
        if device_id!=self.device.get('device_id'):raise PermissionError('iot_device_mismatch')
        if not self.configured():raise IoTAdapterError('AUTH_REQUIRED','IoT target unavailable')
    @staticmethod
    def _bounded(value,limit,label):
        if not isinstance(value,dict):raise ValueError(label+' must be an object')
        if len(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())>limit:raise ValueError(label+' exceeds byte limit')
        return dict(value)
    def _capabilities(self):return tuple(sorted(set(str(x) for x in self.device.get('capabilities',[]) if isinstance(x,str)))[:64])
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,device_id=None,**_):
        self._bind(owner_user_id,device_id);p=dict(payload or {})
        if operation in READ_OPS:
            if set(p)-{'sensor','key'}:raise ValueError('unsupported IoT read argument')
            if operation=='discover':state={}
            else:
                fn=getattr(self.transport,'read_state',None)
                if not callable(fn):raise IoTAdapterError('UNSUPPORTED','IoT state read unavailable')
                state=self._bounded(fn({k:v for k,v in p.items() if v is not None}),MAX_STATE_BYTES,'IoT state')
            obs=IoTObservation(self._reference(),str(self.device.get('kind','iot'))[:40],str(self.device.get('status','UNKNOWN'))[:24],self._capabilities(),state)
            return {'provider':'authenticated IoT transport','operation':operation,'device_reference':self._reference(),'result':obs.to_dict(),'provider_reference':self._reference()}
        if operation in CONTROL_OPS:
            if set(p)-{'action','value'}:raise ValueError('unsupported IoT control argument')
            action=str(p.get('action',''))
            if not action or action in {'gpio','raw_gpio','arbitrary_gpio','raw_pwm','shell','firmware_flash'}:raise PermissionError('unsafe_iot_action_denied')
            caps=set(self._capabilities())
            if action not in caps:raise PermissionError('iot_action_not_declared')
            request=self._bounded({'action':action,'value':p.get('value')},MAX_CONTROL_BYTES,'IoT control request')
            limits=dict(self.device.get('safety_limits') or {})
            allowed_values=(limits.get(action) or {}).get('allowed_values') if isinstance(limits.get(action),dict) else None
            if allowed_values is not None and request['value'] not in allowed_values:raise PermissionError('iot_value_outside_safety_limit')
            fn=getattr(self.transport,'control',None)
            if not callable(fn):raise IoTAdapterError('UNSUPPORTED','IoT control unavailable')
            result=self._bounded(fn(request),MAX_STATE_BYTES,'IoT control result')
            return {'provider':'authenticated IoT transport','operation':operation,'device_reference':self._reference(),'result':{'action':action,'accepted':bool(result.get('accepted'))},'provider_reference':str(result.get('request_reference') or self._reference())[:160]}
        raise KeyError(operation)
    def invoke(self,operation,payload):return self.invoke_with_context(operation,payload,owner_user_id=self.owner_user_id,device_id=self.bound_device_id)
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_):
        if owner_user_id!=self.owner_user_id or not isinstance(result,dict) or result.get('device_reference')!=self._reference():return {'verified':False,'reason':'iot_identity_mismatch'}
        if operation in READ_OPS:return {'verified':self.health().get('ok') is True,'method':'authenticated transport health reread','device_reference':self._reference()}
        fn=getattr(self.transport,'verify',None)
        if not callable(fn):return {'verified':False,'reason':'iot_verifier_unavailable'}
        evidence=fn(result.get('result',{}));return {'verified':bool(isinstance(evidence,dict) and evidence.get('verified') is True),'method':str((evidence or {}).get('method','device state reread')) if isinstance(evidence,dict) else 'device state reread','device_reference':self._reference()}
    def verify(self,operation,result):return self.verify_with_context(operation,result,owner_user_id=self.owner_user_id)
    def close(self):self._closed=True;return {'status':'closed','device_reference':self._reference()}
