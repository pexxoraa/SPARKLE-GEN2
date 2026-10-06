from __future__ import annotations
import hashlib,json,re,uuid
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime,timedelta
from pathlib import PurePosixPath
from typing import Any
from .core_time import now
from .domain.models import ApprovalStatus

GRANTABLE_WRITE_TOOLS=frozenset({'memory_write','workspace_scaffold','workspace_verify','workspace_package'})
_PROJECT_RE=re.compile(r'^[a-z][a-z0-9_-]{1,63}$')
_WORKSPACE_VERIFY_CHECKS=frozenset({'python_compile','javascript_syntax','json_parse'})
_FORBIDDEN_APPROVERS=frozenset({'model','assistant','nemotron','system','system_cancel'})


def _parse_time(value:str|None):
    if not value:return None
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)

def _clean_tool_arguments(arguments):
    value=dict(arguments or {});value.pop('approved',None);value.pop('approval_id',None);value.pop('grant_id',None);return value

def _normalize_granted_arguments(tool,arguments):
    clean=_clean_tool_arguments(arguments)
    if tool=='workspace_scaffold':return DelegationGrantService._validate_workspace_scaffold_arguments(clean)
    if tool=='workspace_verify':return DelegationGrantService._validate_workspace_verify_arguments(clean)
    if tool=='workspace_package':return DelegationGrantService._validate_workspace_package_arguments(clean)
    return clean

@dataclass(slots=True)
class DelegationRequest:
    request_id:str
    goal_id:str
    task_run_id:str
    trace_id:str
    user_id:str
    capability:str
    specialists:list[str]
    objective:str
    inputs:dict[str,Any]=field(default_factory=dict)
    constraints:list[str]=field(default_factory=list)
    deadline:str|None=None
    risk:str='LOW'
    required_evidence:list[str]=field(default_factory=list)
    created_at:str=''
    authorized_action:dict[str,Any]|None=None
    grant_id:str|None=None
    trusted_scope:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class DelegationResult:
    request_id:str
    goal_id:str
    task_run_id:str
    status:str
    specialist_results:list[dict[str,Any]]
    findings:str
    artifacts:list[dict[str,Any]]
    evidence:list[dict[str,Any]]
    confidence:float
    unresolved_items:list[str]
    provenance:dict[str,Any]
    verification:dict[str,Any]
    failure:dict[str,Any]|None=None
    completed_at:str|None=None
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class DelegationRecord:
    request:DelegationRequest
    state:str='PENDING'
    result:DelegationResult|None=None
    updated_at:str=''
    cancellation_requested:bool=False
    def to_dict(self):
        return {'request':self.request.to_dict(),'state':self.state,'result':None if self.result is None else self.result.to_dict(),'updated_at':self.updated_at,'cancellation_requested':self.cancellation_requested}
    @classmethod
    def from_dict(cls,d):
        return cls(DelegationRequest(**d['request']),d['state'],None if d.get('result') is None else DelegationResult(**d['result']),d.get('updated_at',''),bool(d.get('cancellation_requested',False)))

@dataclass(slots=True)
class DelegationGrant:
    grant_id:str
    user_id:str
    goal_id:str
    task_run_id:str
    delegation_request_id:str
    capability:str
    allowed_specialists:list[str]
    allowed_tools:list[str]
    scope:dict[str,Any]
    risk_level:str
    approval_id:str
    issued_at:str
    expires_at:str
    issuer:str
    max_uses:int=1
    uses:int=0
    state:str='ACTIVE'
    consumed_at:str|None=None
    fingerprint:str=''
    def to_dict(self):return asdict(self)

class DelegationGrantService:
    """Authoritative one-shot grants backed by existing Gen-2 Approval records."""
    def __init__(self,store,policy):self.store=store;self.policy=policy
    @staticmethod
    def _binding(grant):
        d=grant.to_dict() if hasattr(grant,'to_dict') else dict(grant)
        return {k:d[k] for k in ('grant_id','user_id','goal_id','task_run_id','delegation_request_id','capability','allowed_specialists','allowed_tools','scope','risk_level','approval_id','issued_at','expires_at','issuer','max_uses')}
    @classmethod
    def fingerprint(cls,grant):return hashlib.sha256(_canonical(cls._binding(grant)).encode()).hexdigest()
    @staticmethod
    def approval_scope(request:DelegationRequest):
        action=dict(request.authorized_action or {});tool=str(action.get('tool',''));args=_clean_tool_arguments(action.get('arguments',{}))
        if tool=='workspace_scaffold':args=DelegationGrantService._validate_workspace_scaffold_arguments(args)
        elif tool=='workspace_verify':args=DelegationGrantService._validate_workspace_verify_arguments(args)
        elif tool=='workspace_package':args=DelegationGrantService._validate_workspace_package_arguments(args)
        return _canonical({'user_id':request.user_id,'goal_id':request.goal_id,'task_run_id':request.task_run_id,'delegation_request_id':request.request_id,'specialists':list(request.specialists),'capability':tool,'tool':tool,'arguments':args,'trusted_scope':dict(request.trusted_scope or {})})
    @staticmethod
    def _validate_workspace_scaffold_arguments(arguments):
        args=_clean_tool_arguments(arguments)
        if set(args)-{'project_name','files','overwrite'}:raise ValueError('workspace scaffold arguments contain unsupported fields')
        project=args.get('project_name');files=args.get('files');overwrite=args.get('overwrite',False)
        if not isinstance(project,str) or not _PROJECT_RE.fullmatch(project):raise ValueError('workspace project identity is invalid')
        if overwrite is not False:raise PermissionError('delegated workspace scaffold requires overwrite=false')
        if not isinstance(files,dict) or not 1<=len(files)<=100:raise ValueError('workspace manifest must contain 1-100 files')
        normalized={};total=0
        for raw_path,content in files.items():
            if not isinstance(raw_path,str) or not isinstance(content,str):raise ValueError('workspace manifest paths and contents must be strings')
            if not raw_path or len(raw_path)>240 or '\0' in raw_path or '\\' in raw_path:raise ValueError('workspace manifest path is invalid')
            path=PurePosixPath(raw_path)
            if path.is_absolute() or any(part in {'','.','..'} for part in path.parts):raise ValueError('workspace manifest path escapes project')
            canonical=path.as_posix()
            if canonical in normalized:raise ValueError('workspace manifest contains duplicate normalized path')
            size=len(content.encode('utf-8'))
            if size>250_000:raise ValueError('workspace manifest file exceeds byte limit')
            total+=size;normalized[canonical]=content
        if total>1_000_000:raise ValueError('workspace manifest exceeds byte limit')
        return {'project_name':project,'files':normalized,'overwrite':False}
    @staticmethod
    def _validate_workspace_verify_arguments(arguments):
        args=_clean_tool_arguments(arguments)
        if set(args)-{'project_name','checks'}:raise ValueError('workspace verify arguments contain unsupported fields')
        project=args.get('project_name');checks=args.get('checks')
        if not isinstance(project,str) or not _PROJECT_RE.fullmatch(project):raise ValueError('workspace project identity is invalid')
        if not isinstance(checks,list) or not 1<=len(checks)<=50:raise ValueError('workspace verification requires 1-50 checks')
        normalized=[]
        for check in checks:
            if not isinstance(check,dict) or set(check)!={'type','path'}:raise ValueError('workspace verification check must contain exactly type and path')
            check_type=check.get('type');raw_path=check.get('path')
            if check_type not in _WORKSPACE_VERIFY_CHECKS:raise ValueError('unsupported workspace verification check type')
            if not isinstance(raw_path,str) or not raw_path or len(raw_path)>240 or '\0' in raw_path or '\\' in raw_path:raise ValueError('workspace verification path is invalid')
            path=PurePosixPath(raw_path)
            if path.is_absolute() or any(part in {'','.','..'} for part in path.parts):raise ValueError('workspace verification path escapes project')
            normalized.append({'type':str(check_type),'path':path.as_posix()})
        return {'project_name':project,'checks':normalized}
    @staticmethod
    def _validate_workspace_package_arguments(arguments):
        args=_clean_tool_arguments(arguments)
        if set(args)!={'project_name'}:raise ValueError('workspace package arguments must contain exactly project_name')
        project=args.get('project_name')
        if not isinstance(project,str) or not _PROJECT_RE.fullmatch(project):raise ValueError('workspace project identity is invalid')
        return {'project_name':project}
    def _validate_request_action(self,request):
        action=request.authorized_action
        if not isinstance(action,dict) or set(action)-{'tool','arguments'}:raise ValueError('authorized action is invalid')
        tool=action.get('tool');arguments=action.get('arguments')
        if tool not in GRANTABLE_WRITE_TOOLS:raise PermissionError('write capability is not grantable through the current specialist boundary')
        if len(request.specialists)!=1:raise PermissionError('write-capable delegation requires exactly one approved specialist')
        if not isinstance(arguments,dict):raise ValueError('authorized action arguments are invalid')
        clean=_clean_tool_arguments(arguments)
        if tool=='workspace_scaffold':
            if request.specialists!=['application_builder']:raise PermissionError('workspace scaffold grant requires application_builder specialist')
            clean=self._validate_workspace_scaffold_arguments(clean)
        elif tool=='workspace_verify':
            if request.specialists!=['application_builder']:raise PermissionError('workspace verify grant requires application_builder specialist')
            clean=self._validate_workspace_verify_arguments(clean)
        elif tool=='workspace_package':
            if request.specialists!=['application_builder']:raise PermissionError('workspace package grant requires application_builder specialist')
            clean=self._validate_workspace_package_arguments(clean)
        permission,risk=self.policy.evaluate(str(tool),'user',self.approval_scope(request),now())
        if permission.effect.value!='REQUIRE_APPROVAL':raise PermissionError('authorized action does not require trusted approval')
        return str(tool),clean,risk
    def issue(self,request:DelegationRequest,approval,*,ttl_seconds=600):
        tool,args,risk=self._validate_request_action(request)
        try:approval=self.store.load_approval(approval.approval_id)
        except (KeyError,AttributeError) as exc:raise PermissionError('authoritative approval not found') from exc
        if approval.status!=ApprovalStatus.APPROVED:raise PermissionError('authoritative approval is not approved')
        if approval.approved_by in _FORBIDDEN_APPROVERS or not approval.approved_by:raise PermissionError('trusted human approval is required')
        if approval.goal_id!=request.goal_id or approval.task_run_id!=request.task_run_id:raise PermissionError('approval correlation mismatch')
        if approval.capability!='specialist_delegate':raise PermissionError('approval capability mismatch')
        if approval.requested_scope!=self.approval_scope(request):raise PermissionError('approval scope mismatch')
        goal=self.store.load_goal(request.goal_id)
        if goal.user_id!=request.user_id:raise PermissionError('approval user identity mismatch')
        approved_expiry=_parse_time(approval.expires_at)
        current=datetime.now(UTC)
        if approved_expiry is not None and approved_expiry<=current:raise PermissionError('approval expired')
        try:
            existing=DelegationGrant(**self.store.delegation_grant_for_request(request.request_id))
            if self.fingerprint(existing)!=existing.fingerprint:raise PermissionError('stored grant integrity failure')
            if existing.approval_id!=approval.approval_id or existing.scope['arguments']!=args or dict(existing.scope.get('trusted_scope') or {})!=dict(request.trusted_scope or {}) or existing.capability!=tool:raise PermissionError('existing grant scope mismatch')
            return existing
        except KeyError:pass
        expires=current+timedelta(seconds=max(30,min(int(ttl_seconds),3600)))
        if approved_expiry is not None:expires=min(expires,approved_expiry)
        grant=DelegationGrant('dgrant_'+uuid.uuid4().hex,request.user_id,request.goal_id,request.task_run_id,request.request_id,tool,list(request.specialists),[tool],{'tool':tool,'arguments':args,'trusted_scope':dict(request.trusted_scope or {})},risk.level.value,approval.approval_id,now(),expires.isoformat(),str(approval.approved_by),1,0,'ACTIVE',None,'')
        grant.fingerprint=self.fingerprint(grant);self.store.save_delegation_grant(grant);return grant
    def load(self,grant_id):
        grant=DelegationGrant(**self.store.load_delegation_grant(grant_id))
        if self.fingerprint(grant)!=grant.fingerprint:raise PermissionError('grant integrity verification failed')
        return grant
    def for_request(self,request_id):
        grant=DelegationGrant(**self.store.delegation_grant_for_request(request_id))
        if self.fingerprint(grant)!=grant.fingerprint:raise PermissionError('grant integrity verification failed')
        return grant
    def revoke_for_request(self,request_id):
        try:grant=self.for_request(request_id)
        except KeyError:return None
        if grant.state=='ACTIVE':grant.state='REVOKED';self.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict())
        return grant
    def check(self,grant_id,*,request:DelegationRequest,specialist,tool,arguments,capability=None):
        grant=self.load(grant_id);approval=self.store.load_approval(grant.approval_id)
        if approval.status!=ApprovalStatus.APPROVED or approval.approved_by!=grant.issuer:raise PermissionError('grant approval is no longer authoritative')
        if grant.state!='ACTIVE' or grant.uses>=grant.max_uses:raise PermissionError('grant is not active')
        if _parse_time(grant.expires_at)<=datetime.now(UTC):
            grant.state='EXPIRED';self.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict());raise PermissionError('grant expired')
        expected=(request.user_id,request.goal_id,request.task_run_id,request.request_id)
        actual=(grant.user_id,grant.goal_id,grant.task_run_id,grant.delegation_request_id)
        if expected!=actual:raise PermissionError('grant parent correlation mismatch')
        if specialist not in grant.allowed_specialists:raise PermissionError('grant specialist mismatch')
        if (capability or tool)!=grant.capability:raise PermissionError('grant capability mismatch')
        if tool not in grant.allowed_tools:raise PermissionError('grant tool mismatch')
        if _normalize_granted_arguments(tool,arguments)!=grant.scope.get('arguments'):raise PermissionError('grant action scope mismatch')
        if dict(request.trusted_scope or {})!=dict(grant.scope.get('trusted_scope') or {}):raise PermissionError('grant trusted scope mismatch')
        return grant
    def consume(self,grant_id,*,request:DelegationRequest,specialist,tool,arguments,capability=None):
        self.check(grant_id,request=request,specialist=specialist,tool=tool,arguments=arguments,capability=capability)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM delegation_grants WHERE grant_id=?',(grant_id,)).fetchone()
            if row is None:raise PermissionError('grant not found')
            grant=DelegationGrant(**json.loads(row[0]))
            if self.fingerprint(grant)!=grant.fingerprint:raise PermissionError('grant integrity verification failed')
            if grant.state!='ACTIVE' or grant.uses>=grant.max_uses:raise PermissionError('grant replay denied')
            if _parse_time(grant.expires_at)<=datetime.now(UTC):raise PermissionError('grant expired')
            grant.uses+=1;grant.state='CONSUMED';grant.consumed_at=now()
            db.execute('UPDATE delegation_grants SET payload=? WHERE grant_id=?',(self.store._dump(grant.to_dict()),grant_id))
        return grant

class DelegationAuthorizationContext:
    """Server-side authority injected into an isolated Gen-1 orchestrator; never model-visible authority."""
    def __init__(self,service,request,catalog):self.service=service;self.request=request;self.catalog={x['name']:x for x in catalog};self.runtime=None;self.execution_verifications=[]
    def _specialist(self,allowed):
        matches=[name for name in self.request.specialists if set(self.catalog.get(name,{}).get('tools',[]))==set(allowed or [])]
        return matches[0] if len(matches)==1 else None
    def visible_tools(self,allowed):
        specialist=self._specialist(allowed);out=[]
        for tool in set(allowed or []):
            permission,_=self.service.policy.evaluate(str(tool),'user',f'specialist:{specialist or "unknown"}',now())
            if permission.effect.value=='ALLOW':out.append(str(tool));continue
            if self.request.grant_id and specialist and tool in GRANTABLE_WRITE_TOOLS:
                try:self.service.grants.check(self.request.grant_id,request=self.request,specialist=specialist,tool=str(tool),arguments=(self.request.authorized_action or {}).get('arguments',{}));out.append(str(tool))
                except PermissionError:pass
        return set(out)
    def authorize(self,name,arguments,allowed):
        specialist=self._specialist(allowed)
        permission,_=self.service.policy.evaluate(str(name),'user',f'specialist:{specialist or "unknown"}',now())
        if permission.effect.value=='ALLOW':return dict(arguments)
        if not self.request.grant_id or not specialist:raise PermissionError('trusted delegation grant required')
        clean=_normalize_granted_arguments(str(name),arguments)
        if self.runtime is not None:
            self.runtime.validate_delegated_action_preconditions(str(name),clean)
            if name=='workspace_package':
                expected=(self.request.trusted_scope or {}).get('package_source');actual=self.runtime.package_source_identity(str(clean.get('project_name','')))
                if expected!=actual:raise PermissionError('package source identity changed after approval')
        self.service.grants.consume(self.request.grant_id,request=self.request,specialist=specialist,tool=str(name),arguments=clean)
        if name in {'workspace_scaffold','workspace_verify','workspace_package'}:clean=dict(clean)|{'approved':True}
        return clean
    def observe(self,name,arguments,output):
        if self.runtime is None:return {'verified':True,'method':'no state-changing delegated verification required'}
        verification=self.runtime.verify_delegated_action(str(name),_clean_tool_arguments(arguments),output)
        if name=='workspace_package':
            expected=(self.request.trusted_scope or {}).get('package_source') or {}
            if verification.get('source_digest')!=expected.get('source_digest'):verification=dict(verification)|{'verified':False,'reason':'approved package source identity mismatch'}
        self.execution_verifications.append({'tool':str(name),'verification':dict(verification)})
        if verification.get('verified') is not True:raise RuntimeError('delegated_action_independent_verification_failed')
        return verification
    def provenance(self):return {'grant_id':self.request.grant_id,'delegation_request_id':self.request.request_id,'approved_action':None if self.request.authorized_action is None else {'tool':self.request.authorized_action.get('tool')},'execution_verifications':list(self.execution_verifications)}

class SpecialistDelegationService:
    """Thin Gen-2 persistence/validation layer over the certified Gen-1 run_multi boundary."""
    CAPABILITY='specialist_delegate'
    def __init__(self,store,gateway,policy):self.store=store;self.gateway=gateway;self.policy=policy;self.grants=DelegationGrantService(store,policy)
    def available(self):return all(callable(getattr(self.gateway,n,None)) for n in ('specialist_catalog','specialist_limits','delegate_specialists'))
    def catalog(self):return list(self.gateway.specialist_catalog()) if self.available() else []
    def limits(self):return dict(self.gateway.specialist_limits()) if self.available() else {}
    @staticmethod
    def deterministic_id(goal_id,task_run_id,step_id,specialists,objective,authorized_action=None):
        raw='|'.join([goal_id,task_run_id,step_id,','.join(specialists),' '.join(objective.split()),_canonical(authorized_action or {})]);return 'dlg_'+hashlib.sha256(raw.encode()).hexdigest()[:32]
    def validate(self,request:DelegationRequest):
        if not self.available():raise RuntimeError('specialist_delegation_unavailable')
        if not request.request_id or not request.goal_id or not request.task_run_id or not request.trace_id:raise ValueError('delegation correlation is required')
        if not isinstance(request.user_id,str) or not request.user_id.strip() or len(request.user_id)>256:raise ValueError('delegation user identity is invalid')
        if not isinstance(request.objective,str) or not request.objective.strip() or len(request.objective)>12000:raise ValueError('delegation objective is invalid')
        if not isinstance(request.specialists,list) or not request.specialists:raise ValueError('delegation requires specialists')
        if any(not isinstance(x,str) or not x for x in request.specialists):raise ValueError('specialist names are invalid')
        if len(set(request.specialists))!=len(request.specialists):raise ValueError('duplicate specialist names are not allowed')
        limits=self.limits();maximum=int(limits.get('max_specialists',0))
        if maximum<1 or len(request.specialists)>maximum:raise ValueError('specialist count exceeds certified bound')
        catalog={x['name']:x for x in self.catalog()};unknown=sorted(set(request.specialists)-set(catalog))
        if unknown:raise ValueError('unknown specialist:'+','.join(unknown))
        unsafe={}
        for name in request.specialists:
            blocked=[]
            for tool in catalog[name].get('tools',[]):
                permission,_=self.policy.evaluate(str(tool),'user',f'specialist:{name}',now())
                if permission.effect.value!='ALLOW':blocked.append(str(tool))
            if blocked:unsafe[name]=blocked
        if unsafe:
            if request.authorized_action is None:
                detail=';'.join(f"{name}:{','.join(sorted(tools))}" for name,tools in sorted(unsafe.items()))
                raise PermissionError('specialist_requires_nondelegable_authority:'+detail)
            tool,_,_=self.grants._validate_request_action(request)
            if tool not in set(catalog[request.specialists[0]].get('tools',[])):raise PermissionError('approved tool is not available to approved specialist')
        elif request.authorized_action is not None:raise PermissionError('authorized action is unnecessary for read-only delegation')
        if request.risk not in {'LOW','MEDIUM','HIGH','CRITICAL'}:raise ValueError('delegation risk is invalid')
        return True
    def prepare(self,request:DelegationRequest):
        self.validate(request)
        try:return self.load(request.request_id)
        except KeyError:pass
        record=DelegationRecord(request,'PENDING',None,now(),False);self.store.save_delegation(record);return record
    def load(self,request_id):return DelegationRecord.from_dict(self.store.load_delegation(request_id))
    def attach_grant(self,request_id,grant_id):
        record=self.load(request_id);record.request.grant_id=grant_id;record.updated_at=now();self.store.save_delegation(record);return record
    def cancel(self,request_id):
        record=self.load(request_id)
        if record.state in {'COMPLETED','FAILED','BLOCKED','CANCELLED'}:return record
        record.cancellation_requested=True
        if record.state=='PENDING':record.state='CANCELLED'
        else:record.state='CANCEL_REQUESTED'
        record.updated_at=now();self.store.save_delegation(record);self.grants.revoke_for_request(request_id);return record
    def reconcile(self,request_id):
        record=self.load(request_id)
        if record.state!='WAITING' or record.result is None:return record.result
        pending=list(record.result.provenance.get('pending_approvals',[]));states=[]
        for item in pending:
            state=self.gateway.approval_status(item.get('approval_id'),item.get('tool'));states.append(state)
        if any(str(x.get('status','')).upper() in {'REJECTED','EXPIRED','CANCELLED'} for x in states):
            record.state='FAILED';record.result.status='FAILED';record.result.verification={'verified':False,'method':'delegated Gen-1 approval rejected','approvals':states};record.result.failure={'category':'APPROVAL','reason':'delegated Gen-1 approval rejected'}
        elif states and all(str(x.get('status','')).upper()=='APPROVED' and x.get('verified') is True for x in states):
            record.state='COMPLETED';record.result.status='COMPLETED';record.result.verification={'verified':True,'method':'delegated Gen-1 approval reconciliation and authoritative state reread','approvals':states};record.result.evidence.extend([{'approval':x} for x in states]);record.result.provenance['reconciled_approvals']=states
        record.updated_at=now();self.store.save_delegation(record);return record.result
    def execute(self,request:DelegationRequest):
        record=self.prepare(request)
        if record.state=='COMPLETED' and record.result is not None:return record.result
        if record.state=='WAITING' and record.result is not None:return record.result
        if record.state=='CANCELLED':
            return DelegationResult(request.request_id,request.goal_id,request.task_run_id,'CANCELLED',[],'',[],[],0.0,['cancelled before execution'],{'trace_id':request.trace_id},{'verified':False,'method':'cancelled before Gen-1 execution'},{'category':'CANCELLED','reason':'cancelled before execution'},now())
        if record.state in {'RUNNING','CANCEL_REQUESTED'}:
            record.state='BLOCKED';record.updated_at=now();self.store.save_delegation(record)
            return DelegationResult(request.request_id,request.goal_id,request.task_run_id,'BLOCKED',[],'',[],[],0.0,['in-flight delegation cannot be resumed after restart'],{'trace_id':request.trace_id},{'verified':False,'method':'Gen-1 synchronous delegation is not restart-resumable'},{'category':'RESTART_BOUNDARY','reason':'in-flight delegation not resumable'},now())
        if request.authorized_action is not None:
            if not request.grant_id:raise PermissionError('approved delegation grant required')
            self.grants.check(request.grant_id,request=request,specialist=request.specialists[0],tool=str(request.authorized_action.get('tool')),arguments=request.authorized_action.get('arguments',{}))
        record.state='RUNNING';record.updated_at=now();self.store.save_delegation(record)
        input_source='gen2-delegation:'+request.request_id
        payload={'objective':request.objective,'inputs':request.inputs,'constraints':request.constraints,'deadline':request.deadline,'risk':request.risk,'required_evidence':request.required_evidence}
        if request.authorized_action is not None:payload['approved_action']={'tool':request.authorized_action.get('tool'),'arguments':_clean_tool_arguments(request.authorized_action.get('arguments',{}))}
        execution_text='GEN2_DELEGATION_REQUEST='+_canonical(payload)
        if len(execution_text)>12000:raise ValueError('delegation payload exceeds bound')
        authorization=None if request.authorized_action is None else DelegationAuthorizationContext(self,request,self.catalog())
        try:
            if authorization is None:raw=self.gateway.delegate_specialists(execution_text,request.specialists,user_id=request.user_id,input_source=input_source)
            else:raw=self.gateway.delegate_specialists(execution_text,request.specialists,user_id=request.user_id,input_source=input_source,authorization=authorization)
            current=self.load(request.request_id)
            if current.cancellation_requested:
                result=DelegationResult(request.request_id,request.goal_id,request.task_run_id,'CANCELLED',list(raw.get('specialist_results',[])),'',[],list(raw.get('evidence',[])),0.0,['cancellation requested during synchronous Gen-1 execution'],dict(raw.get('provenance',{}))|{'trace_id':request.trace_id},{'verified':False,'method':'result discarded after cancellation request'},{'category':'CANCELLED','reason':'cancellation requested during execution'},now())
                current.state='CANCELLED';current.result=result;current.updated_at=now();self.store.save_delegation(current);return result
            verification=dict(raw.get('verification',{}));status=str(raw.get('status','FAILED'))
            result=DelegationResult(request.request_id,request.goal_id,request.task_run_id,status,list(raw.get('specialist_results',[])),str(raw.get('findings',''))[:12000],list(raw.get('artifacts',[])),list(raw.get('evidence',[])),float(raw.get('confidence',0.0)),list(raw.get('unresolved_items',[])),dict(raw.get('provenance',{}))|{'parent_trace_id':request.trace_id,'user_id':request.user_id,'grant_id':request.grant_id},verification,raw.get('failure'),now())
            current.state='COMPLETED' if status=='COMPLETED' and verification.get('verified') is True else ('WAITING' if status=='WAITING_APPROVAL' else 'FAILED');current.result=result;current.updated_at=now();self.store.save_delegation(current);return result
        except Exception as exc:
            current=self.load(request.request_id);result=DelegationResult(request.request_id,request.goal_id,request.task_run_id,'FAILED',[],'',[],[],0.0,[str(exc)[:300]],{'parent_trace_id':request.trace_id,'user_id':request.user_id,'grant_id':request.grant_id},{'verified':False,'method':'Gen-1 specialist delegation failed'},{'category':getattr(exc,'orchestration_code',type(exc).__name__),'reason':str(exc)[:300]},now());current.state='FAILED';current.result=result;current.updated_at=now();self.store.save_delegation(current);return result
