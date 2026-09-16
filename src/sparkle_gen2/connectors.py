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
    granted_scopes:list[str]=field(default_factory=list)
    def public_dict(self):
        d=asdict(self);d.pop('adapter',None);return d

class ConnectorManager:
    def __init__(self): self._records={}
    def register(self,record:ConnectorRecord):
        if record.name in self._records: raise ValueError('duplicate connector')
        if len(set(record.scopes))!=len(record.scopes): raise ValueError('duplicate scope')
        if set(record.granted_scopes)-set(record.scopes):raise ValueError('granted scope exceeds declared scope')
        if record.adapter is not None and not record.granted_scopes:
            # Backward-compatible trusted local adapter registration. External adapters should use authorize/connect.
            record.granted_scopes=list(record.scopes);record.status='CONNECTED'
        self._records[record.name]=record;return record.public_dict()
    def discover(self): return [self._records[k].public_dict() for k in sorted(self._records)]
    def authorize(self,name,scopes):
        r=self._records[name];requested=list(scopes)
        if not requested or len(set(requested))!=len(requested):raise ValueError('authorization scopes required and unique')
        if set(requested)-set(r.scopes):raise PermissionError('scope_not_declared')
        r.granted_scopes=requested;r.status='AUTHORIZED';return r.public_dict()
    def connect(self,name,adapter):
        r=self._records[name]
        if not r.granted_scopes:raise PermissionError('connector_not_authorized')
        r.adapter=adapter;r.status='CONNECTED';return self.health(name)
    def health(self,name):
        r=self._records[name]
        if r.adapter is None:
            status='EXTERNALLY_BLOCKED' if r.external_dependency and r.status not in {'AUTHORIZED','REVOKED'} else r.status
            return {'name':name,'status':status,'dependency':r.external_dependency,'granted_scopes':list(r.granted_scopes)}
        return {'name':name,'status':'CONNECTED','detail':r.adapter.health(),'granted_scopes':list(r.granted_scopes)}
    def invoke(self,name,operation,payload,required_scope):
        r=self._records[name]
        if required_scope not in r.scopes: raise PermissionError('scope_not_declared')
        if required_scope not in r.granted_scopes: raise PermissionError('scope_not_granted')
        if r.adapter is None: raise RuntimeError(f'external_dependency:{r.external_dependency or name}')
        result=r.adapter.invoke(operation,dict(payload))
        return {'connector':name,'operation':operation,'result':result}
    def verify(self,name,operation,result):
        r=self._records[name]
        if r.adapter is None:raise RuntimeError(f'external_dependency:{r.external_dependency or name}')
        verifier=getattr(r.adapter,'verify',None)
        if verifier is None:return {'verified':False,'reason':'adapter_has_no_verifier'}
        evidence=verifier(operation,result)
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:return {'verified':False,'reason':'verification_failed'}
        return evidence
    def revoke(self,name):
        r=self._records[name];r.adapter=None;r.granted_scopes=[];r.status='REVOKED';return r.public_dict()
