from __future__ import annotations
import hashlib,json,re

MAX_TOPIC_CHARS=256
MAX_MESSAGE_BYTES=32_000
TOPIC_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9/_-]{0,255}$')

class MQTTAdapter:
    """Bounded MQTT transport adapter over an already-authenticated broker client.

    The adapter never creates credentials or widens topic scope. ConnectorManager composition
    additionally binds owner/device identity and central policy/approval semantics.
    """
    provider='authenticated MQTT broker transport'
    def __init__(self,client=None,*,allowed_topics=None,require_authenticated=True,require_tls=True,owner_user_id='user',device_id=None):
        self.client=client;self.allowed_topics=set(allowed_topics or []);self.require_authenticated=bool(require_authenticated);self.require_tls=bool(require_tls);self.owner_user_id=str(owner_user_id);self.device_id=None if device_id is None else str(device_id);self._closed=False
        for topic in self.allowed_topics:self._validate_topic(topic)
    @property
    def bound_device_id(self):return self.device_id if self.configured() else None
    @staticmethod
    def _digest(value):return hashlib.sha256(str(value).encode()).hexdigest()[:24]
    def _device_reference(self):return None if not self.device_id else 'mqtt-device:'+self._digest(self.device_id)
    def configured(self):return bool(self.client is not None and self.allowed_topics and not self._closed)
    def authorize(self):
        if not self.configured() or not self.device_id:raise RuntimeError('external_dependency:mqtt_authenticated_device')
        h=self.health()
        if h.get('ok') is not True:raise RuntimeError('mqtt_transport_unhealthy')
        return {'authorization_reference':'mqtt-auth:'+self._digest(self.device_id),'device_id':self.device_id,'granted_scopes':['mqtt.read','mqtt.publish']}
    @staticmethod
    def _validate_topic(topic):
        if not isinstance(topic,str) or not TOPIC_RE.fullmatch(topic) or '+' in topic or '#' in topic:raise ValueError('invalid mqtt topic')
        return topic
    def health(self):
        if self._closed:return {'ok':False,'status':'UNAVAILABLE','authorization_state':'REVOKED','device_reference':self._device_reference()}
        if self.client is None:return {'ok':False,'status':'EXTERNALLY_BLOCKED','authorization_state':'REQUIRED','dependency':'mqtt broker/device credentials','device_reference':self._device_reference()}
        try:h=self.client.health()
        except Exception:return {'ok':False,'status':'BLOCKED','authorization_state':'AUTHORIZED' if self.device_id else 'REQUIRED','reason':'mqtt_health_failure','device_reference':self._device_reference()}
        if not isinstance(h,dict):return {'ok':False,'status':'BLOCKED','authorization_state':'AUTHORIZED' if self.device_id else 'REQUIRED','reason':'mqtt_health_invalid','device_reference':self._device_reference()}
        ok=bool(h.get('ok'));authenticated=h.get('authenticated');tls=h.get('tls')
        if self.require_authenticated and (authenticated is False or (self.device_id and authenticated is not True)):ok=False
        if self.require_tls and (tls is False or (self.device_id and tls is not True)):ok=False
        return {'ok':ok,'status':'HEALTHY' if ok else 'BLOCKED','authorization_state':'AUTHORIZED' if self.device_id else 'REQUIRED','authenticated':authenticated,'tls':tls,'device_reference':self._device_reference()}
    def _topic(self,payload):
        topic=self._validate_topic(payload.get('topic'))
        if topic not in self.allowed_topics:raise PermissionError('mqtt_topic_not_allowlisted')
        return topic
    @staticmethod
    def _bounded_message(value):
        try:raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        except Exception as exc:raise ValueError('mqtt message is not serializable') from exc
        if len(raw)>MAX_MESSAGE_BYTES:raise ValueError('mqtt message exceeds byte limit')
        return value
    def _bind(self,owner_user_id,device_id):
        if self._closed:raise PermissionError('mqtt_adapter_revoked')
        if owner_user_id!=self.owner_user_id:raise PermissionError('mqtt_owner_mismatch')
        if not self.device_id:raise PermissionError('mqtt_device_identity_required')
        if device_id!=self.device_id:raise PermissionError('mqtt_device_mismatch')
    def _invoke(self,operation,payload):
        if self.client is None:raise RuntimeError('external_dependency:mqtt')
        if self.health().get('ok') is not True:raise RuntimeError('mqtt_transport_unhealthy')
        p=dict(payload or {})
        if operation=='read':
            if set(p)-{'topic'}:raise ValueError('unsupported mqtt read argument')
            topic=self._topic(p);result=self._bounded_message(self.client.read(topic))
        elif operation=='publish':
            if set(p)-{'topic','message'}:raise ValueError('unsupported mqtt publish argument')
            topic=self._topic(p);message=self._bounded_message(p.get('message'));result=self._bounded_message(self.client.publish(topic,message))
        else:raise PermissionError('mqtt_operation_not_allowlisted')
        return result
    def invoke(self,operation,payload):return self._invoke(operation,payload)
    def invoke_with_context(self,operation,payload,*,owner_user_id=None,device_id=None,**_context):
        self._bind(owner_user_id,device_id);result=self._invoke(operation,payload);topic=str((payload or {}).get('topic',''))
        return {'provider':self.provider,'operation':operation,'device_reference':self._device_reference(),'result':result,'provider_reference':'mqtt-ref:'+self._digest(topic)}
    def _verify_result(self,operation,result):
        if self.client is None:return {'verified':False,'reason':'mqtt_not_connected'}
        if self.health().get('ok') is not True:return {'verified':False,'reason':'mqtt_transport_unhealthy'}
        v=self.client.verify(operation,result);return v if isinstance(v,dict) and v.get('verified') is True else {'verified':False,'reason':'verification_failed'}
    def verify(self,operation,result):return self._verify_result(operation,result)
    def verify_with_context(self,operation,result,*,owner_user_id=None,**_context):
        if owner_user_id!=self.owner_user_id:return {'verified':False,'reason':'mqtt_owner_mismatch'}
        if not isinstance(result,dict) or result.get('provider')!=self.provider or result.get('operation')!=operation or result.get('device_reference')!=self._device_reference():return {'verified':False,'reason':'mqtt_identity_mismatch'}
        evidence=self._verify_result(operation,result.get('result'))
        if evidence.get('verified') is not True:return {'verified':False,'reason':'verification_failed','method':str(evidence.get('method','broker reread'))}
        return {'verified':True,'method':str(evidence.get('method','broker reread')),'device_reference':self._device_reference(),'verification_digest':hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    def close(self):self._closed=True;return {'status':'closed','device_reference':self._device_reference()}
