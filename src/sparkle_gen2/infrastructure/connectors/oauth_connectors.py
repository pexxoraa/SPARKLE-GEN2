from __future__ import annotations
from dataclasses import dataclass,field,asdict

@dataclass(slots=True)
class OAuthConnection:
    provider:str
    account_ref:str
    granted_scopes:list[str]
    connection_id:str
    status:str='CONNECTED'
    metadata:dict=field(default_factory=dict)
    def public_dict(self):return asdict(self)

class OAuthConnectorAdapter:
    """Credential-reference OAuth adapter. Secret/token values remain inside the injected transport/vault."""
    def __init__(self,provider,declared_scopes,transport):
        self.provider=provider;self.declared_scopes=set(declared_scopes);self.transport=transport;self.connection=None
    def authorize(self,account_ref,secret_ref,scopes):
        requested=list(scopes)
        if not requested or set(requested)-self.declared_scopes:raise PermissionError('oauth_scope_not_declared')
        if not isinstance(secret_ref,str) or not secret_ref.strip():raise ValueError('secret_reference_required')
        result=self.transport.connect(self.provider,account_ref,secret_ref,requested)
        if not isinstance(result,dict) or not result.get('connection_id'):raise RuntimeError('oauth_connection_failed')
        self.connection=OAuthConnection(self.provider,account_ref,requested,str(result['connection_id']),'CONNECTED',dict(result.get('metadata',{})));return self.connection.public_dict()
    def health(self):
        if self.connection is None:return {'ok':False,'status':'EXTERNALLY_BLOCKED','dependency':'oauth account/credential reference'}
        detail=self.transport.health(self.connection.connection_id)
        return {'ok':bool(detail.get('ok')),'status':'CONNECTED' if detail.get('ok') else 'BLOCKED','connection_id':self.connection.connection_id,'granted_scopes':list(self.connection.granted_scopes)}
    def invoke(self,operation,payload):
        if self.connection is None:raise RuntimeError('oauth_not_connected')
        result=self.transport.invoke(self.connection.connection_id,operation,dict(payload))
        if not isinstance(result,dict):raise RuntimeError('oauth_invalid_observation')
        return result
    def verify(self,operation,result):
        if self.connection is None:return {'verified':False,'reason':'oauth_not_connected'}
        evidence=self.transport.verify(self.connection.connection_id,operation,result)
        return evidence if isinstance(evidence,dict) and evidence.get('verified') is True else {'verified':False,'reason':'verification_failed'}
    def revoke(self):
        if self.connection is None:return {'revoked':False,'reason':'not_connected'}
        cid=self.connection.connection_id;result=self.transport.revoke(cid)
        if not isinstance(result,dict) or result.get('revoked') is not True:raise RuntimeError('oauth_revoke_failed')
        self.connection.status='REVOKED';self.connection=None;return {'revoked':True,'connection_id':cid}
