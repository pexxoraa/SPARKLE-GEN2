from __future__ import annotations
import hashlib,json,uuid
from dataclasses import asdict,dataclass,field
from enum import Enum
from typing import Any,Protocol
from .core_time import now
from .models import ApprovalStatus,PermissionEffect

FORBIDDEN_AUTH_FIELDS=frozenset({'approved','approval_id','grant_id','authorization_override','access_token','refresh_token','authorization','cookie','api_key','secret','password','credential'})
PROTECTED_EXTERNAL=frozenset({'SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'})

class ConnectorLifecycleState(str,Enum):
    UNCONFIGURED='UNCONFIGURED';DISCOVERED='DISCOVERED';CONNECTING='CONNECTING';CONNECTED='CONNECTED';AUTH_REQUIRED='AUTH_REQUIRED';AUTHORIZED='AUTHORIZED';HEALTHY='HEALTHY';DEGRADED='DEGRADED';UNAVAILABLE='UNAVAILABLE';BLOCKED='BLOCKED';REVOKED='REVOKED';FAILED='FAILED'
class ConnectorAuthorizationState(str,Enum):
    NOT_REQUIRED='NOT_REQUIRED';NOT_CONFIGURED='NOT_CONFIGURED';REQUIRED='REQUIRED';PENDING='PENDING';AUTHORIZED='AUTHORIZED';EXPIRED='EXPIRED';REVOKED='REVOKED';FAILED='FAILED'
class ConnectorHealthState(str,Enum):
    UNKNOWN='UNKNOWN';HEALTHY='HEALTHY';DEGRADED='DEGRADED';UNAVAILABLE='UNAVAILABLE';BLOCKED='BLOCKED';FAILED='FAILED'
class ConnectorOperationMode(str,Enum):READ='READ';WRITE='WRITE';CONTROL='CONTROL'
class ConnectorAuthorizationMode(str,Enum):NONE='NONE';SECRET='SECRET';OAUTH='OAUTH';DEVICE='DEVICE';EXTERNAL='EXTERNAL'

class Connector(Protocol):
    def health(self)->dict[str,Any]:...
    def invoke(self,operation:str,payload:dict[str,Any])->dict[str,Any]:...
    def verify(self,operation:str,result:dict[str,Any])->dict[str,Any]:...
ConnectorAdapter=Connector

@dataclass(frozen=True,slots=True)
class ConnectorCapability:
    capability:str;operation:str;scope:str;mode:ConnectorOperationMode=ConnectorOperationMode.READ;policy_capability:str='connector_read';description:str=''
    def to_dict(self):
        d=asdict(self);d['mode']=self.mode.value;return d

@dataclass(frozen=True,slots=True)
class ConnectorDescriptor:
    connector_id:str;display_name:str;provider_system:str;capabilities:tuple[ConnectorCapability,...];authorization_mode:ConnectorAuthorizationMode=ConnectorAuthorizationMode.EXTERNAL;secret_refs:tuple[str,...]=();external_dependency:str|None=None;device_scoped:bool=False;metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):
        d=asdict(self);d['authorization_mode']=self.authorization_mode.value;d['capabilities']=[x.to_dict() for x in self.capabilities];d['secret_refs']=list(self.secret_refs);return d

@dataclass(slots=True)
class ConnectorConnection:
    connector_id:str;owner_user_id:str;state:ConnectorLifecycleState;authorization_state:ConnectorAuthorizationState;granted_scopes:list[str]=field(default_factory=list);connected_at:str|None=None;last_checked:str|None=None;last_error:str|None=None;provenance:dict[str,Any]=field(default_factory=dict);capabilities:list[str]=field(default_factory=list)
    def to_dict(self):
        d=asdict(self);d['state']=self.state.value;d['authorization_state']=self.authorization_state.value;return d
@dataclass(frozen=True,slots=True)
class ConnectorAuthorization:
    connector_id:str;owner_user_id:str;state:ConnectorAuthorizationState;granted_scopes:tuple[str,...];actor:str;reference:str|None;updated_at:str
    def to_dict(self):
        d=asdict(self);d['state']=self.state.value;d['granted_scopes']=list(self.granted_scopes);return d
@dataclass(frozen=True,slots=True)
class ConnectorHealth:
    connector_id:str;owner_user_id:str;state:ConnectorHealthState;lifecycle_state:ConnectorLifecycleState;checked_at:str;reason:str|None=None;detail:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):
        d=asdict(self);d['state']=self.state.value;d['lifecycle_state']=self.lifecycle_state.value;return d
@dataclass(frozen=True,slots=True)
class ConnectorInvocation:
    request_id:str;connector_id:str;operation:str;owner_user_id:str;goal_id:str|None;task_run_id:str|None;trace_id:str|None;classification:str;risk:str;authorization_state:str;approval_reference:str|None;arguments_digest:str;created_at:str
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class ConnectorVerification:
    request_id:str;verified:bool;method:str;status:str;evidence:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)
@dataclass(frozen=True,slots=True)
class ConnectorRevocation:
    connector_id:str;owner_user_id:str;revoked_at:str;actor:str;previous_state:str
    def to_dict(self):return asdict(self)

# Backward-compatible legacy registration structure.
@dataclass(slots=True)
class ConnectorRecord:
    name:str;scopes:list[str];status:str;adapter:ConnectorAdapter|None=None;external_dependency:str|None=None;metadata:dict[str,Any]=field(default_factory=dict);granted_scopes:list[str]=field(default_factory=list)
    def public_dict(self):d=asdict(self);d.pop('adapter',None);return d

class ConnectorManager:
    """Owner-scoped connector lifecycle/policy projection over existing connector adapters."""
    def __init__(self,store=None,*,policy=None,secrets=None,default_owner='user'):
        self.store=store;self.policy=policy;self.secrets=secrets;self.default_owner=default_owner;self._descriptors={};self._adapters={};self._legacy=set();self._memory_states={};self._memory_invocations={}
    @staticmethod
    def _canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    @staticmethod
    def _clean_args(arguments):
        if not isinstance(arguments,dict):raise ValueError('connector arguments must be an object')
        if any(str(k).lower() in FORBIDDEN_AUTH_FIELDS for k in arguments):raise PermissionError('model_supplied_connector_authority_rejected')
        raw=json.dumps(arguments,ensure_ascii=False,separators=(',',':'))
        if len(raw.encode())>200_000:raise ValueError('connector arguments exceed bounded size')
        return dict(arguments)
    @staticmethod
    def _scope_for_legacy(scope):
        op=scope.split('.')[-1] if '.' in scope else scope;mode=ConnectorOperationMode.WRITE if op in {'send','write','create','delete','commit','push','execute','control','command','move','publish','act'} else ConnectorOperationMode.READ;policy='connector_write' if mode!=ConnectorOperationMode.READ else 'connector_read';return ConnectorCapability(scope,op,scope,mode,policy)
    def register(self,record):
        if isinstance(record,ConnectorDescriptor):return self.register_descriptor(record)
        if not isinstance(record,ConnectorRecord):raise TypeError('connector registration requires ConnectorDescriptor or ConnectorRecord')
        if record.name in self._descriptors:raise ValueError('duplicate connector')
        if len(set(record.scopes))!=len(record.scopes):raise ValueError('duplicate scope')
        if set(record.granted_scopes)-set(record.scopes):raise ValueError('granted scope exceeds declared scope')
        desc=ConnectorDescriptor(record.name,record.name.title(),record.name,tuple(self._scope_for_legacy(x) for x in record.scopes),ConnectorAuthorizationMode.NONE if record.adapter is not None else ConnectorAuthorizationMode.EXTERNAL,(),record.external_dependency,False,dict(record.metadata));self.register_descriptor(desc,adapter=record.adapter);self._legacy.add(record.name)
        if record.adapter is not None:
            st=self._state(record.name,self.default_owner);st.granted_scopes=list(record.granted_scopes or record.scopes);st.authorization_state=ConnectorAuthorizationState.AUTHORIZED;st.state=ConnectorLifecycleState.CONNECTED;self._save_state(st)
        elif record.granted_scopes:
            st=self._state(record.name,self.default_owner);st.granted_scopes=list(record.granted_scopes);st.authorization_state=ConnectorAuthorizationState.AUTHORIZED;st.state=ConnectorLifecycleState.AUTHORIZED;self._save_state(st)
        return self.inspect(record.name,owner_user_id=self.default_owner)
    def register_descriptor(self,descriptor,*,adapter=None):
        if not isinstance(descriptor,ConnectorDescriptor):raise TypeError('descriptor required')
        cid=descriptor.connector_id
        if not cid or cid in self._descriptors:raise ValueError('duplicate connector')
        caps=list(descriptor.capabilities);ops=[x.operation for x in caps];cap_names=[x.capability for x in caps]
        if not caps or len(ops)!=len(set(ops)) or len(cap_names)!=len(set(cap_names)):raise ValueError('connector capabilities and operations must be unique')
        self._descriptors[cid]=descriptor
        if adapter is not None:self._adapters[cid]=adapter
        return descriptor.to_dict()
    def _default_state(self,cid,owner):
        d=self._descriptors[cid];auth=ConnectorAuthorizationState.NOT_REQUIRED if d.authorization_mode==ConnectorAuthorizationMode.NONE else (ConnectorAuthorizationState.NOT_CONFIGURED if d.secret_refs else ConnectorAuthorizationState.REQUIRED);state=ConnectorLifecycleState.DISCOVERED if d.authorization_mode==ConnectorAuthorizationMode.NONE else ConnectorLifecycleState.AUTH_REQUIRED
        return ConnectorConnection(cid,owner,state,auth,[],None,None,None,{'source':'connector_registry'},[x.capability for x in d.capabilities])
    def _state(self,cid,owner):
        if cid not in self._descriptors:raise KeyError(cid)
        key=(owner,cid);payload=None
        if self.store is not None:payload=self.store.connector_state(cid,owner_user_id=owner)
        else:payload=self._memory_states.get(key)
        if payload is None:return self._default_state(cid,owner)
        p=dict(payload);p['state']=ConnectorLifecycleState(p['state']);p['authorization_state']=ConnectorAuthorizationState(p['authorization_state']);return ConnectorConnection(**p)
    def _save_state(self,state):
        if self.store is not None:self.store.save_connector_state(state)
        else:self._memory_states[(state.owner_user_id,state.connector_id)]=state.to_dict()
    def descriptor(self,cid):return self._descriptors[cid]
    def capabilities(self,cid):return [x.to_dict() for x in self._descriptors[cid].capabilities]
    def discover(self,owner_user_id=None):
        owner=owner_user_id or self.default_owner;out=[]
        for cid in sorted(self._descriptors):
            d=self._descriptors[cid];st=self._state(cid,owner);row=d.to_dict()|{'name':cid,'scopes':sorted({x.scope for x in d.capabilities}),'status':self._public_status(d,st),'state':st.state.value,'authorization_state':st.authorization_state.value,'granted_scopes':list(st.granted_scopes),'configured':self._configured(d),'connected':cid in self._adapters and st.state in {ConnectorLifecycleState.CONNECTED,ConnectorLifecycleState.HEALTHY,ConnectorLifecycleState.DEGRADED},'authorized':st.authorization_state in {ConnectorAuthorizationState.NOT_REQUIRED,ConnectorAuthorizationState.AUTHORIZED},'healthy':st.state==ConnectorLifecycleState.HEALTHY}
            out.append(row)
        return out
    def _configured(self,d):
        adapter=self._adapters.get(d.connector_id);configured=getattr(adapter,'configured',None)
        if callable(configured):
            try:return bool(configured())
            except Exception:return False
        if d.secret_refs:
            if self.secrets is None:return False
            try:return all(self.secrets.status(d.secret_refs).values())
            except Exception:return False
        if d.authorization_mode==ConnectorAuthorizationMode.NONE:return (not d.external_dependency) or d.connector_id in self._adapters
        return d.connector_id in self._adapters
    @staticmethod
    def _public_status(d,st):
        if st.state==ConnectorLifecycleState.REVOKED:return 'REVOKED'
        if st.state==ConnectorLifecycleState.HEALTHY:return 'HEALTHY'
        if st.state in {ConnectorLifecycleState.CONNECTED,ConnectorLifecycleState.AUTHORIZED}:return st.state.value
        if d.external_dependency:return 'EXTERNALLY_BLOCKED'
        return st.state.value
    def inspect(self,name,*,owner_user_id=None):
        owner=owner_user_id or self.default_owner;row=next(x for x in self.discover(owner) if x['connector_id']==name);row['operations']=[{'operation':x.operation,'capability':x.capability,'scope':x.scope,'mode':x.mode.value,'policy_capability':x.policy_capability} for x in self._descriptors[name].capabilities];return row
    def authorize(self,name,scopes,*,owner_user_id=None,actor='trusted_system',reference=None,state='AUTHORIZED'):
        owner=owner_user_id or self.default_owner;d=self._descriptors[name];requested=list(scopes)
        if not requested or len(set(requested))!=len(requested):raise ValueError('authorization scopes required and unique')
        declared={x.scope for x in d.capabilities}
        if set(requested)-declared:raise PermissionError('scope_not_declared')
        auth=ConnectorAuthorizationState(state)
        if auth!=ConnectorAuthorizationState.AUTHORIZED:raise ValueError('authorize requires AUTHORIZED state')
        st=self._state(name,owner);st.granted_scopes=requested;st.authorization_state=auth;st.state=ConnectorLifecycleState.AUTHORIZED;st.last_error=None;st.provenance={'authorization_actor':actor,'authorization_reference':reference,'updated_at':now()};self._save_state(st);return ConnectorAuthorization(name,owner,auth,tuple(requested),actor,reference,now()).to_dict()
    def set_authorization_state(self,name,state,*,owner_user_id=None,actor='trusted_system',reference=None):
        owner=owner_user_id or self.default_owner;value=ConnectorAuthorizationState(state)
        if value in {ConnectorAuthorizationState.AUTHORIZED,ConnectorAuthorizationState.NOT_REQUIRED}:raise ValueError('use authorize/connect lifecycle for positive authorization state')
        st=self._state(name,owner);st.authorization_state=value
        if value in {ConnectorAuthorizationState.REQUIRED,ConnectorAuthorizationState.PENDING,ConnectorAuthorizationState.NOT_CONFIGURED}:st.state=ConnectorLifecycleState.AUTH_REQUIRED
        elif value==ConnectorAuthorizationState.REVOKED:st.state=ConnectorLifecycleState.REVOKED;st.granted_scopes=[];st.connected_at=None
        elif value==ConnectorAuthorizationState.EXPIRED:st.state=ConnectorLifecycleState.AUTH_REQUIRED;st.granted_scopes=[]
        else:st.state=ConnectorLifecycleState.FAILED
        st.last_checked=now();st.provenance={'authorization_actor':actor,'authorization_reference':reference,'updated_at':st.last_checked};self._save_state(st);return ConnectorAuthorization(name,owner,value,tuple(st.granted_scopes),actor,reference,st.last_checked).to_dict()
    def authorization_required(self,name,*,owner_user_id=None):
        owner=owner_user_id or self.default_owner;d=self._descriptors[name];st=self._state(name,owner);return {'connector_id':name,'owner_user_id':owner,'authorization_mode':d.authorization_mode.value,'authorization_state':st.authorization_state.value,'required_secret_refs':list(d.secret_refs),'configured':self._configured(d),'granted_scopes':list(st.granted_scopes)}
    def connect(self,name,adapter=None,*,owner_user_id=None):
        owner=owner_user_id or self.default_owner;d=self._descriptors[name];st=self._state(name,owner);ad=adapter or self._adapters.get(name)
        if st.state==ConnectorLifecycleState.REVOKED:raise PermissionError('connector_revoked')
        if d.secret_refs and not self._configured(d):raise PermissionError('connector_not_configured')
        if ad is None:
            st.state=ConnectorLifecycleState.UNAVAILABLE;st.last_error='connector_adapter_unavailable';self._save_state(st);return self.health(name,owner_user_id=owner)
        if d.authorization_mode!=ConnectorAuthorizationMode.NONE and st.authorization_state!=ConnectorAuthorizationState.AUTHORIZED:raise PermissionError('connector_not_authorized')
        st.state=ConnectorLifecycleState.CONNECTING;st.last_checked=now();self._save_state(st);self._adapters[name]=ad;st.state=ConnectorLifecycleState.CONNECTED;st.connected_at=st.connected_at or now();st.last_error=None;self._save_state(st);return self.health(name,owner_user_id=owner)
    def health(self,name,*,owner_user_id=None):
        owner=owner_user_id or self.default_owner;d=self._descriptors[name];st=self._state(name,owner);ad=self._adapters.get(name);stamp=now()
        if st.state==ConnectorLifecycleState.REVOKED:return {'name':name,'connector_id':name,'status':'REVOKED','state':'REVOKED','authorization_state':st.authorization_state.value,'granted_scopes':list(st.granted_scopes),'dependency':d.external_dependency,'owner_user_id':owner}
        if ad is None:
            if d.authorization_mode!=ConnectorAuthorizationMode.NONE and st.authorization_state!=ConnectorAuthorizationState.AUTHORIZED:
                st.state=ConnectorLifecycleState.AUTH_REQUIRED;reason='authorization_required' if self._configured(d) else 'external_dependency_or_credential_unavailable'
            else:st.state=ConnectorLifecycleState.UNAVAILABLE;reason='connector_adapter_unavailable'
            st.last_checked=stamp;st.last_error=reason;self._save_state(st);return {'name':name,'connector_id':name,'status':'EXTERNALLY_BLOCKED' if d.external_dependency else st.state.value,'state':st.state.value,'health':'UNAVAILABLE','authorization_state':st.authorization_state.value,'configured':self._configured(d),'granted_scopes':list(st.granted_scopes),'dependency':d.external_dependency,'reason':reason,'owner_user_id':owner}
        try:
            detail=ad.health();ok=bool(detail.get('ok',detail.get('status') in {'HEALTHY','CONNECTED','AVAILABLE'})) if isinstance(detail,dict) else False
            auth_value=detail.get('authorization_state') if isinstance(detail,dict) else None
            if auth_value in {x.value for x in ConnectorAuthorizationState}:st.authorization_state=ConnectorAuthorizationState(auth_value)
            if st.authorization_state==ConnectorAuthorizationState.REVOKED:st.state=ConnectorLifecycleState.REVOKED;st.last_error='authorization_revoked';health=ConnectorHealthState.BLOCKED
            elif d.authorization_mode!=ConnectorAuthorizationMode.NONE and st.authorization_state in {ConnectorAuthorizationState.NOT_CONFIGURED,ConnectorAuthorizationState.REQUIRED,ConnectorAuthorizationState.PENDING,ConnectorAuthorizationState.EXPIRED}:st.state=ConnectorLifecycleState.AUTH_REQUIRED;st.last_error=str((detail or {}).get('error_category') or 'authorization_required');health=ConnectorHealthState.UNAVAILABLE
            elif d.authorization_mode!=ConnectorAuthorizationMode.NONE and st.authorization_state==ConnectorAuthorizationState.FAILED:st.state=ConnectorLifecycleState.FAILED;st.last_error=str((detail or {}).get('error_category') or 'authorization_failed');health=ConnectorHealthState.FAILED
            else:st.state=ConnectorLifecycleState.HEALTHY if ok else ConnectorLifecycleState.DEGRADED;st.last_error=None if ok else str((detail or {}).get('error_category') or 'connector_health_degraded');health=ConnectorHealthState.HEALTHY if ok else ConnectorHealthState.DEGRADED
        except Exception as exc:
            detail={};st.state=ConnectorLifecycleState.FAILED;st.last_error=type(exc).__name__;health=ConnectorHealthState.FAILED
        st.last_checked=stamp;self._save_state(st);public_status='CONNECTED' if name in self._legacy and st.state==ConnectorLifecycleState.HEALTHY else st.state.value;return {'name':name,'connector_id':name,'status':public_status,'state':st.state.value,'health':health.value,'authorization_state':st.authorization_state.value,'configured':self._configured(d),'granted_scopes':list(st.granted_scopes),'dependency':d.external_dependency,'detail':detail,'owner_user_id':owner,'last_checked':stamp,'reason':st.last_error}
    def _capability(self,name,operation,required_scope=None):
        d=self._descriptors[name];cap=next((x for x in d.capabilities if x.operation==operation),None)
        if cap is None and required_scope is not None:cap=next((x for x in d.capabilities if x.scope==required_scope),None)
        if cap is None:
            if required_scope is not None:raise PermissionError('scope_not_declared')
            raise KeyError(operation)
        if required_scope is not None and cap.scope!=required_scope:raise PermissionError('scope_operation_mismatch')
        return cap
    @staticmethod
    def _approval_ok(approval,*,goal_id,task_run_id):
        if approval is None:return False
        status=getattr(approval,'status',None);status=getattr(status,'value',status)
        if status!='APPROVED':return False
        if goal_id is not None and getattr(approval,'goal_id',None)!=goal_id:return False
        if task_run_id is not None and getattr(approval,'task_run_id',None)!=task_run_id:return False
        return True
    def _save_invocation(self,payload):
        if self.store is not None:self.store.save_connector_invocation(payload)
        else:self._memory_invocations[payload['request_id']]=dict(payload)
    def invocations(self,*,owner_user_id=None,connector_id=None):
        owner=owner_user_id or self.default_owner
        if self.store is not None:return self.store.connector_invocations(owner_user_id=owner,connector_id=connector_id)
        return [dict(v) for v in self._memory_invocations.values() if v.get('owner_user_id')==owner and (connector_id is None or v.get('connector_id')==connector_id)]
    def invoke(self,name,operation,payload,required_scope=None,*,owner_user_id=None,goal_id=None,task_run_id=None,trace_id=None,classification='PRIVATE',risk='LOW',approval=None,request_id=None,device_id=None):
        owner=owner_user_id or self.default_owner;d=self._descriptors[name];cap=self._capability(name,operation,required_scope);arguments=self._clean_args(payload);classification=str(classification).upper()
        if classification not in {'PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL'}:raise ValueError('invalid connector classification')
        if d.external_dependency and classification in PROTECTED_EXTERNAL:raise PermissionError('classification_prohibits_external_connector_transmission')
        ad=self._adapters.get(name);bound_device=getattr(ad,'bound_device_id',None) if ad is not None else None
        if callable(bound_device):bound_device=bound_device()
        if d.device_scoped:
            if device_id is None and isinstance(bound_device,str) and bound_device:device_id=bound_device
            if not device_id:raise PermissionError('device_scoped_connector_requires_device_identity')
            if isinstance(bound_device,str) and bound_device and device_id!=bound_device:raise PermissionError('device_scoped_connector_identity_mismatch')
        st=self._state(name,owner)
        if st.state==ConnectorLifecycleState.REVOKED:raise PermissionError('connector_revoked')
        if d.authorization_mode!=ConnectorAuthorizationMode.NONE:
            if st.authorization_state!=ConnectorAuthorizationState.AUTHORIZED:raise PermissionError('connector_not_authorized')
            if cap.scope not in st.granted_scopes:raise PermissionError('scope_not_granted')
        elif st.granted_scopes and cap.scope not in st.granted_scopes:raise PermissionError('scope_not_granted')
        permission=None;risk_eval=None
        if self.policy is not None:
            permission,risk_eval=self.policy.evaluate(cap.policy_capability,owner,f'{name}:{operation}',now())
            if permission.effect==PermissionEffect.DENY:raise PermissionError('connector_policy_denied')
            if permission.effect==PermissionEffect.REQUIRE_APPROVAL and not self._approval_ok(approval,goal_id=goal_id,task_run_id=task_run_id):raise PermissionError('connector_approval_required')
        if ad is None:raise RuntimeError(f'external_dependency:{d.external_dependency or name}')
        digest=hashlib.sha256(self._canon(arguments).encode()).hexdigest();rid=request_id or 'conn_'+hashlib.sha256(self._canon({'owner':owner,'connector':name,'operation':operation,'goal_id':goal_id,'task_run_id':task_run_id,'trace_id':trace_id,'arguments_digest':digest,'device_id':device_id}).encode()).hexdigest()[:32];existing=next((x for x in self.invocations(owner_user_id=owner,connector_id=name) if x.get('request_id')==rid and x.get('verification_status')=='VERIFIED'),None)
        if existing is not None and cap.mode!=ConnectorOperationMode.READ:return {'connector':name,'operation':operation,'request_id':rid,'status':'VERIFIED','result':existing.get('result_summary',{}),'verification':existing.get('verification',{}),'reused':True,'provenance':existing.get('provenance',{})}
        auth_state='ALLOW' if permission is None or permission.effect==PermissionEffect.ALLOW else 'APPROVED';approval_ref=getattr(approval,'approval_id',None) if approval is not None else None;inv=ConnectorInvocation(rid,name,operation,owner,goal_id,task_run_id,trace_id,classification,getattr(getattr(risk_eval,'level',None),'value',risk),auth_state,approval_ref,digest,now());base=inv.to_dict()|{'capability':cap.capability,'scope':cap.scope,'mode':cap.mode.value,'device_id':device_id,'status':'INVOKING','verification_status':'PENDING','external_reference':None,'result_summary':{},'verification':{},'provenance':{'provider_system':d.provider_system,'policy_capability':cap.policy_capability,'secret_refs':list(d.secret_refs)}};self._save_invocation(base)
        try:
            contextual=getattr(ad,'invoke_with_context',None);result=contextual(operation,arguments,owner_user_id=owner,goal_id=goal_id,task_run_id=task_run_id,trace_id=trace_id,classification=classification,approval=approval,device_id=device_id) if contextual is not None else ad.invoke(operation,arguments)
        except TimeoutError as exc:
            failed=base|{'status':'FAILED','verification_status':'FAILED','failure':{'type':'TimeoutError','category':'timeout'}};self._save_invocation(failed);raise
        except Exception as exc:
            failed=base|{'status':'FAILED','verification_status':'FAILED','failure':{'type':type(exc).__name__,'category':str(getattr(exc,'category','connector_failure'))}};self._save_invocation(failed);raise
        verification=self.verify(name,operation,result,request_id=rid,owner_user_id=owner);status='VERIFIED' if verification.get('verified') else 'FAILED';summary={'keys':sorted(result)[:30]} if isinstance(result,dict) else {'type':type(result).__name__};external_ref=(result.get('external_request_id') or result.get('provider_reference')) if isinstance(result,dict) else None;stored=base|{'status':status,'verification_status':'VERIFIED' if verification.get('verified') else 'FAILED','external_reference':external_ref,'result_summary':summary,'verification':verification,'provenance':base['provenance']|{'verified_at':now()}};self._save_invocation(stored)
        return {'connector':name,'operation':operation,'request_id':rid,'status':status,'result':result,'verification':verification,'reused':False,'provenance':stored['provenance']}
    def invoke_read(self,name,operation,payload,required_scope=None,**context):
        cap=self._capability(name,operation,required_scope)
        if cap.mode!=ConnectorOperationMode.READ:raise PermissionError('connector_read_tool_cannot_invoke_mutation')
        return self.invoke(name,operation,payload,required_scope,**context)
    def verify(self,name,operation,result,*,request_id=None,owner_user_id=None):
        ad=self._adapters.get(name)
        if ad is None:raise RuntimeError(f'external_dependency:{self._descriptors[name].external_dependency or name}')
        contextual=getattr(ad,'verify_with_context',None);verifier=getattr(ad,'verify',None)
        if contextual is None and verifier is None:return {'verified':False,'reason':'adapter_has_no_verifier','method':'none'}
        evidence=contextual(operation,result,owner_user_id=owner_user_id or self.default_owner,request_id=request_id) if contextual is not None else verifier(operation,result)
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:return {'verified':False,'reason':'verification_failed','method':str((evidence or {}).get('method','adapter_verifier')) if isinstance(evidence,dict) else 'adapter_verifier'}
        return dict(evidence)|({'request_id':request_id} if request_id else {})
    def close(self):
        closed=[]
        for name,adapter in list(self._adapters.items()):
            closer=getattr(adapter,'close',None)
            if not callable(closer):continue
            try:
                closer();closed.append(name)
            except Exception:
                continue
        return {'closed_connectors':sorted(closed)}

    def revoke(self,name,*,owner_user_id=None,actor='trusted_system'):
        owner=owner_user_id or self.default_owner;st=self._state(name,owner);previous=st.state.value;adapter=self._adapters.get(name);closer=getattr(adapter,'close',None)
        if callable(closer):
            try:closer()
            except Exception:pass
        st.granted_scopes=[];st.authorization_state=ConnectorAuthorizationState.REVOKED;st.state=ConnectorLifecycleState.REVOKED;st.connected_at=None;st.last_checked=now();st.last_error=None;self._save_state(st)
        if name in self._legacy:self._adapters.pop(name,None)
        return ConnectorRevocation(name,owner,now(),actor,previous).to_dict()
