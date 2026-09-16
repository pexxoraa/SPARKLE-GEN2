from __future__ import annotations

class MQTTAdapter:
    def __init__(self,client=None,*,allowed_topics=None):self.client=client;self.allowed_topics=set(allowed_topics or [])
    def health(self):
        if self.client is None:return {'ok':False,'status':'EXTERNALLY_BLOCKED','dependency':'mqtt broker/device credentials'}
        h=self.client.health();return {'ok':bool(h.get('ok')),'status':'CONNECTED' if h.get('ok') else 'BLOCKED'}
    def _topic(self,payload):
        topic=str(payload.get('topic',''))
        if topic not in self.allowed_topics:raise PermissionError('mqtt_topic_not_allowlisted')
        return topic
    def invoke(self,operation,payload):
        if self.client is None:raise RuntimeError('external_dependency:mqtt')
        topic=self._topic(payload)
        if operation=='read':return self.client.read(topic)
        if operation=='publish':return self.client.publish(topic,payload.get('message'))
        raise PermissionError('mqtt_operation_not_allowlisted')
    def verify(self,operation,result):
        if self.client is None:return {'verified':False,'reason':'mqtt_not_connected'}
        v=self.client.verify(operation,result);return v if isinstance(v,dict) and v.get('verified') is True else {'verified':False,'reason':'verification_failed'}
