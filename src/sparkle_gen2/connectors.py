from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

class ConnectorAdapter(Protocol):
    def health(self)->dict[str,Any]: ...
    def invoke(self,operation:str,payload:dict[str,Any])->dict[str,Any]: ...

@dataclass(slots=True)
class ConnectorRecord:
    name:str
    scopes:list[str]
    status:str
    adapter:ConnectorAdapter|None=None
    external_dependency:str|None=None
    metadata:dict[str,Any]=field(default_factory=dict)
    def public_dict(self):
        d=asdict(self);d.pop('adapter',None);return d

class ConnectorManager:
    def __init__(self): self._records={}
    def register(self,record:ConnectorRecord):
        if record.name in self._records: raise ValueError('duplicate connector')
        if len(set(record.scopes))!=len(record.scopes): raise ValueError('duplicate scope')
        self._records[record.name]=record
    def discover(self): return [self._records[k].public_dict() for k in sorted(self._records)]
    def health(self,name):
        r=self._records[name]
        if r.adapter is None:return {'name':name,'status':'EXTERNALLY_BLOCKED','dependency':r.external_dependency}
        return {'name':name,'status':'CONNECTED','detail':r.adapter.health()}
    def invoke(self,name,operation,payload,required_scope):
        r=self._records[name]
        if required_scope not in r.scopes: raise PermissionError('scope_not_granted')
        if r.adapter is None: raise RuntimeError(f'external_dependency:{r.external_dependency or name}')
        result=r.adapter.invoke(operation,dict(payload))
        return {'connector':name,'operation':operation,'result':result}
    def revoke(self,name):
        r=self._records[name];r.adapter=None;r.status='REVOKED';return r.public_dict()
