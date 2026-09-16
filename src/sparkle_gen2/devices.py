from __future__ import annotations
from dataclasses import asdict, dataclass
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
    def public_dict(self):
        d=asdict(self);d.pop('adapter',None);return d
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
        if action not in {'status','read'} and not approved:raise PermissionError('approval_required')
        return r.adapter.invoke(action,dict(payload))
