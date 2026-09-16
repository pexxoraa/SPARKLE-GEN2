from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Protocol

class DeviceAdapter(Protocol):
    def status(self)->dict: ...
    def invoke(self,action:str,payload:dict)->dict: ...
@dataclass(slots=True)
class DeviceRecord:
    device_id:str
    kind:str
    status:str
    adapter:DeviceAdapter|None=None
    external_dependency:str|None=None
    connection:dict=field(default_factory=dict)
    capabilities:list[str]=field(default_factory=list)
    permissions:list[str]=field(default_factory=list)
    safety_limits:dict=field(default_factory=dict)
    firmware:str|None=None
    last_seen:str|None=None
    def public_dict(self):
        d=asdict(self);d.pop('adapter',None);d['type']=d['kind'];return d
class DeviceManager:
    def __init__(self):self.records={}
    def register(self,r):
        if r.device_id in self.records:raise ValueError('duplicate device')
        self.records[r.device_id]=r
    def discover(self):return [self.records[k].public_dict() for k in sorted(self.records)]
    def health(self,device_id):
        r=self.records[device_id]
        if r.adapter is None:return {'status':'EXTERNALLY_BLOCKED','dependency':r.external_dependency}
        return {'status':'CONNECTED','detail':r.adapter.status()}
    def invoke(self,device_id,action,payload,*,approved=False):
        r=self.records[device_id]
        if r.adapter is None:raise RuntimeError('external_dependency:'+str(r.external_dependency))
        if action in {'raw_gpio','arbitrary_gpio','gpio','raw_pwm'}:raise PermissionError('unsafe_direct_gpio_control')
        if r.capabilities and action not in set(r.capabilities)|{'status','read'}:raise PermissionError('device_capability_not_declared')
        if action not in {'status','read'} and not approved:raise PermissionError('approval_required')
        return r.adapter.invoke(action,dict(payload))

    def verify(self,device_id,action,result):
        r=self.records[device_id]
        if r.adapter is None:raise RuntimeError('external_dependency:'+str(r.external_dependency))
        verifier=getattr(r.adapter,'verify',None)
        if verifier is None:return {'verified':False,'reason':'adapter_has_no_verifier'}
        evidence=verifier(action,result)
        return evidence if isinstance(evidence,dict) and evidence.get('verified') is True else {'verified':False,'reason':'verification_failed'}
    def invoke_verified(self,device_id,action,payload,*,approved=False):
        result=self.invoke(device_id,action,payload,approved=approved);verification=self.verify(device_id,action,result)
        if verification.get('verified') is not True:raise RuntimeError('device_verification_failed')
        return {'result':result,'verification':verification}
