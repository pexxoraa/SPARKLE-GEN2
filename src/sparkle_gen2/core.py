from __future__ import annotations
import json,uuid
from time import monotonic
from datetime import UTC,datetime,timedelta
from typing import Any
from .core_time import now
from .gen1 import Gen1Gateway,ToolObservation
from .failures import FailureClassifier
from .delegation import DelegationRequest,SpecialistDelegationService
from .models import *
from .memory_orchestration import MemoryCandidateService
from .learning_orchestration import LearningOrchestrator
from .automation_orchestration import AutomationOrchestrator
from .observability import TraceRecorder
from .planner import Gen1PlannerModel,PlannerError,PlannerModel
from .policy import PolicyEngine
from .permission_center import PermissionCenter
from .storage import Gen2Store
from .validation import PlanValidationError,PlanValidator

class PersonalAgent:
    def __init__(self,store:Gen2Store,gen1:Gen1Gateway,*,planner:PlannerModel|None=None,policy:PolicyEngine|None=None,context_provider=None,connector_manager=None,document_service=None,image_service=None,perception_service=None,daily_os_service=None,operations_service=None,notification_service=None,learning_service=None,tracer=None,max_iterations:int=12,planner_retries:int=1,max_replans:int=1):
        if not 1<=max_iterations<=100:raise ValueError('max_iterations out of range')
        if not 0<=planner_retries<=2:raise ValueError('planner_retries out of range')
        if not 0<=max_replans<=3:raise ValueError('max_replans out of range')
        self.store=store;self.gen1=gen1;self.planner=planner or Gen1PlannerModel(gen1);self.policy=policy or PolicyEngine();self.context_provider=context_provider;self.connectors=connector_manager;self.documents=document_service;self.images=image_service;self.perception=perception_service;self.daily_os=daily_os_service;self.operations=operations_service;self.notifications=notification_service;self.notification_delivery=getattr(notification_service,'delivery',None);self.learning=learning_service;self.traces=tracer or TraceRecorder(store);self.memory=MemoryCandidateService(store,gen1,self.policy);self.delegation=SpecialistDelegationService(store,gen1,self.policy);self.failures=FailureClassifier();self.max_iterations=max_iterations;self.planner_retries=planner_retries;self.max_replans=max_replans
        self._execution_health_cache=None
        self._execution_health_cache_at=0.0
        self._execution_health_ttl=5.0
        self.automation=AutomationOrchestrator(store,gen1,lambda:self) if AutomationOrchestrator.available(gen1) else None
    def _goal(self,request,user_id='user',target_device_id=None,target_device_kind=None):
        stamp=now();constraints=[]
        if target_device_id:constraints.append('target_device_id:'+str(target_device_id))
        if target_device_kind:constraints.append('target_device_kind:'+str(target_device_kind))
        return Goal(uuid.uuid4().hex,request.strip(),' '.join(request.strip().split()),constraints=constraints,success_criteria=[],context_requirements=['relevant Gen-1 context'],created_at=stamp,updated_at=stamp,status=GoalStatus.CREATED,user_id=user_id)
    def _execution_health(self):
        stamp=monotonic()
        if self._execution_health_cache is not None and stamp-self._execution_health_cache_at < self._execution_health_ttl:
            base=dict(self._execution_health_cache)
        else:
            base=dict(self.gen1.health())
            self._execution_health_cache=dict(base)
            self._execution_health_cache_at=stamp
        tools=list(base.get('tools',[]));definitions=list(base.get('tool_definitions',[]))
        if self.delegation.available() and 'specialist_delegate' not in tools:
            tools.append('specialist_delegate');definitions.append({'name':'specialist_delegate','description':'Delegate bounded read-only analysis to certified Gen-1 specialists. Specialists are explicit, unique, allowlisted, and retain Gen-1 tool restrictions.','parameters':{'type':'object','properties':{'specialists':{'type':'array','items':{'type':'string'},'minItems':1},'objective':{'type':'string'},'inputs':{'type':'object'},'constraints':{'type':'array','items':{'type':'string'}},'required_evidence':{'type':'array','items':{'type':'string'}},'authorized_action':{'type':'object','properties':{'tool':{'type':'string'},'arguments':{'type':'object'}},'required':['tool','arguments'],'additionalProperties':False}},'required':['specialists','objective'],'additionalProperties':False}})
        if self.notifications is not None:
            defs=[
                {'name':'notification_inspect','description':'Inspect one persisted notification owned by the current user using bounded attention evidence.','parameters':{'type':'object','properties':{'notification_id':{'type':'string'}},'required':['notification_id'],'additionalProperties':False}},
                {'name':'notification_explain','description':'Explain why one persisted notification surfaced using deterministic persisted decision evidence.','parameters':{'type':'object','properties':{'notification_id':{'type':'string'}},'required':['notification_id'],'additionalProperties':False}},
            ]
            if self.notification_delivery is not None:
                defs.extend([
                    {'name':'notification_delivery_inspect','description':'Inspect persisted delivery attempts and channel outcomes for one owned notification or attempt.','parameters':{'type':'object','properties':{'notification_id':{'type':'string'},'attempt_id':{'type':'string'}},'additionalProperties':False}},
                    {'name':'notification_channels_inspect','description':'Inspect current persisted notification-channel availability for the current user.','parameters':{'type':'object','properties':{},'additionalProperties':False}},
                    {'name':'notification_delivery_retry','description':'Retry one eligible failed/unavailable/expired notification delivery. Requires approval.','parameters':{'type':'object','properties':{'attempt_id':{'type':'string'}},'required':['attempt_id'],'additionalProperties':False}},
                    {'name':'notification_acknowledge','description':'Acknowledge one accepted notification delivery. Requires approval when performed by PersonalAgent.','parameters':{'type':'object','properties':{'attempt_id':{'type':'string'}},'required':['attempt_id'],'additionalProperties':False}},
                ])
            for d in defs:
                if d['name'] not in tools:tools.append(d['name']);definitions.append(d)
        if self.connectors is not None:
            defs=[
                {'name':'connector_list','description':'List registered connectors and bounded owner-scoped lifecycle/availability state. Read-only.','parameters':{'type':'object','properties':{},'additionalProperties':False}},
                {'name':'connector_inspect','description':'Inspect one registered connector, its operations, authorization state, and availability. Read-only.','parameters':{'type':'object','properties':{'connector_id':{'type':'string'}},'required':['connector_id'],'additionalProperties':False}},
                {'name':'connector_capabilities','description':'List typed operations/capabilities for one connector. Read-only.','parameters':{'type':'object','properties':{'connector_id':{'type':'string'}},'required':['connector_id'],'additionalProperties':False}},
                {'name':'connector_health','description':'Recheck one connector through its existing adapter/transport and return bounded health evidence. Read-only.','parameters':{'type':'object','properties':{'connector_id':{'type':'string'}},'required':['connector_id'],'additionalProperties':False}},
                {'name':'connector_read','description':'Invoke one exact registered READ operation through ConnectorManager. It cannot invoke connector writes/control and still obeys connector authorization, owner isolation, classification, central policy, and verification.','parameters':{'type':'object','properties':{'connector_id':{'type':'string'},'operation':{'type':'string'},'arguments':{'type':'object'},'classification':{'type':'string','enum':['PUBLIC','PRIVATE']},'device_id':{'type':'string'}},'required':['connector_id','operation','arguments'],'additionalProperties':False}},
                {'name':'connector_invoke','description':'Invoke one exact registered connector mutation/control operation through ConnectorManager. Requires human approval at the PersonalAgent boundary and still obeys underlying connector policy/authorization/verification.','parameters':{'type':'object','properties':{'connector_id':{'type':'string'},'operation':{'type':'string'},'arguments':{'type':'object'},'classification':{'type':'string','enum':['PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL']},'device_id':{'type':'string'}},'required':['connector_id','operation','arguments'],'additionalProperties':False}},
            ]
            for d in defs:
                if d['name'] not in tools:tools.append(d['name']);definitions.append(d)
        if self.operations is not None and 'operations_snapshot' not in tools:
            tools.append('operations_snapshot');definitions.append({'name':'operations_snapshot','description':'Read the bounded persisted Personal Operations Surface for the current user: Daily Brief, active work, approvals, blockers, capability/provider state, devices/world freshness and diagnostics.','parameters':{'type':'object','properties':{'day':{'type':'string'}},'additionalProperties':False}})
        if self.daily_os is not None:
            defs=[
                {'name':'daily_brief_generate','description':'Generate or reuse a persisted deterministic daily priority brief from bounded Personal Context.','parameters':{'type':'object','properties':{'day':{'type':'string'},'focus':{'type':'string'},'max_items':{'type':'integer','minimum':1,'maximum':50}},'additionalProperties':False}},
                {'name':'daily_brief_inspect','description':'Inspect a persisted daily brief owned by the current user.','parameters':{'type':'object','properties':{'brief_id':{'type':'string'},'day':{'type':'string'}},'additionalProperties':False}},
                {'name':'daily_brief_update','description':'Mark one daily brief item DONE or DISMISSED. Requires approval.','parameters':{'type':'object','properties':{'brief_id':{'type':'string'},'item_id':{'type':'string'},'state':{'type':'string','enum':['DONE','DISMISSED']}},'required':['brief_id','item_id','state'],'additionalProperties':False}},
                {'name':'daily_brief_close','description':'Close one persisted daily brief. Requires approval.','parameters':{'type':'object','properties':{'brief_id':{'type':'string'}},'required':['brief_id'],'additionalProperties':False}},
            ]
            for d in defs:
                if d['name'] not in tools:tools.append(d['name']);definitions.append(d)
        if self.perception is not None and 'perception_observe' not in tools:
            tools.append('perception_observe');definitions.append({'name':'perception_observe','description':'Read one registered robot perception source, normalize it, update fresh world state, and return provenance/freshness. Read-only observation only.','parameters':{'type':'object','properties':{'robot_id':{'type':'string'}},'required':['robot_id'],'additionalProperties':False}})
        if self.images is not None and 'image_generate' not in tools:
            tools.append('image_generate');definitions.append({'name':'image_generate','description':'Generate exactly one bounded image through the routed image_generation model and persist it in the authoritative artifact store. Requires approval.','parameters':{'type':'object','properties':{'prompt':{'type':'string'},'height':{'type':'integer','minimum':256,'maximum':2048},'width':{'type':'integer','minimum':256,'maximum':2048},'samples':{'type':'integer','enum':[1]},'seed':{'type':'integer','minimum':0,'maximum':4294967295},'steps':{'type':'integer','minimum':1,'maximum':50},'classification':{'type':'string','enum':['PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL']}},'required':['prompt'],'additionalProperties':False}})
        if self.documents is not None:
            if 'document_ingest' not in tools:
                tools.append('document_ingest');definitions.append({'name':'document_ingest','description':'Validate, extract, structure, and persist one named file already present in the private Gen-2 documents root. This is approval-gated and never accepts arbitrary host paths.','parameters':{'type':'object','properties':{'filename':{'type':'string'},'classification':{'type':'string','enum':['PUBLIC','PRIVATE','SENSITIVE','HIGHLY_SENSITIVE','DEVICE_CONTROL']}},'required':['filename'],'additionalProperties':False}})
            if 'document_search' not in tools:
                tools.append('document_search');definitions.append({'name':'document_search','description':'Search READY documents owned by the current user using bounded deterministic lexical retrieval with source provenance.','parameters':{'type':'object','properties':{'query':{'type':'string'},'document_id':{'type':'string'},'k':{'type':'integer','minimum':1,'maximum':20}},'required':['query'],'additionalProperties':False}})
        if self.learning is not None:
            learning_defs=[
                {'name':'learning_plan_create','description':'Create one bounded persistent learning curriculum from explicit approved units and verified Gen-1 progress evidence when available. Requires approval.','parameters':{'type':'object','properties':{'subject':{'type':'string'},'objective':{'type':'string'},'units':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':20}},'required':['subject','objective','units'],'additionalProperties':False}},
                {'name':'learning_plan_inspect','description':'Inspect one owner-scoped persisted adaptive learning plan, weaknesses, retraining state, and provenance.','parameters':{'type':'object','properties':{'plan_id':{'type':'string'}},'required':['plan_id'],'additionalProperties':False}},
                {'name':'learning_assess','description':'Record one exact human-approved bounded assessment score and evidence reference; mastery/weakness is computed deterministically. Requires approval.','parameters':{'type':'object','properties':{'plan_id':{'type':'string'},'unit_id':{'type':'string'},'score':{'type':'number','minimum':0,'maximum':1},'evidence_reference':{'type':'string'}},'required':['plan_id','unit_id','score','evidence_reference'],'additionalProperties':False}},
            ]
            for d in learning_defs:
                if d['name'] not in tools:tools.append(d['name']);definitions.append(d)
        if self.automation is not None:
            auto_defs=[
                {'name':'automation_create','description':'Create a bounded persistent automation that launches a normal Gen-2 goal through the reliable automation/background boundary.','parameters':{'type':'object','properties':{'name':{'type':'string'},'trigger_type':{'type':'string','enum':['scheduled','event','condition','deadline']},'prompt':{'type':'string'},'schedule_kind':{'type':'string','enum':['once','daily','weekly']},'schedule':{'type':'string'},'next_run_at':{'type':'string'},'condition':{'type':'object'},'required_capabilities':{'type':'array','items':{'type':'string'}},'max_attempts':{'type':'integer'},'time_budget_seconds':{'type':'number'}},'required':['name','trigger_type','prompt'],'additionalProperties':False}},
                *[{'name':f'automation_{op}','description':f'{op.title()} a Gen-2-owned automation through the authoritative Gen-1 automation store.','parameters':{'type':'object','properties':{'automation_id':{'type':'integer'}},'required':['automation_id'],'additionalProperties':False}} for op in ('pause','resume','cancel','disable','run_now')],
            ]
            for d in auto_defs:
                if d['name'] not in tools:tools.append(d['name']);definitions.append(d)
        base['tools']=sorted(set(tools));base['tool_definitions']=definitions;return base
    def invalidate_execution_health_cache(self):
        self._execution_health_cache=None
        self._execution_health_cache_at=0.0

    @staticmethod
    def _schema_argument_error(step,schemas):
        """Return a deterministic argument-validation error, or None."""
        args=step.arguments
        if not isinstance(args,dict):
            return {'error':'invalid_arguments','reason':'tool arguments must be an object'}
        schema=schemas.get(step.preferred_tool) if isinstance(schemas,dict) else None
        if not isinstance(schema,dict):
            return None
        parameters=schema.get('parameters') or {}
        if not isinstance(parameters,dict):
            return None
        properties=parameters.get('properties') or {}
        if not isinstance(properties,dict):
            properties={}
        required=parameters.get('required') or []
        for name in required:
            if name not in args:
                return {'error':'missing_required_argument','argument':name}
            value=args.get(name)
            if value is None or (isinstance(value,str) and not value.strip()):
                return {'error':'missing_required_argument','argument':name}
        if parameters.get('additionalProperties') is False:
            extras=sorted(set(args)-set(properties))
            if extras:
                return {'error':'unexpected_arguments','arguments':extras}
        return None

    def _validate_plan_arguments(self,plan,schemas,goal=None):
        """Validate planner arguments and preserve an explicit target-device constraint."""
        errors=[];target_device_id=None;target_device_kind=None
        if goal is not None:
            for constraint in list(goal.constraints or []):
                if isinstance(constraint,str) and constraint.startswith('target_device_id:'):
                    target_device_id=constraint.split(':',1)[1].strip() or None
                elif isinstance(constraint,str) and constraint.startswith('target_device_kind:'):
                    target_device_kind=constraint.split(':',1)[1].strip().lower() or None
        expected_connector={'computer':'computer','linux':'linux','mobile':'mobile'}.get(target_device_kind)
        for step in plan.steps:
            if target_device_id and step.preferred_tool in {'connector_read','connector_invoke'}:
                props=((schemas.get(step.preferred_tool) or {}).get('parameters') or {}).get('properties') or {}
                if 'device_id' in props:
                    current=step.arguments.get('device_id')
                    if not current:step.arguments['device_id']=target_device_id
                    elif str(current)!=target_device_id:errors.append({'step_id':step.step_id,'tool':step.preferred_tool,'error':'target_device_mismatch'})
                if expected_connector and str(step.arguments.get('connector_id','')).lower()!=expected_connector:
                    errors.append({'step_id':step.step_id,'tool':step.preferred_tool,'error':'target_connector_mismatch','expected_connector':expected_connector})
            elif target_device_kind and expected_connector and step.preferred_tool in {'connector_read','connector_invoke'}:
                if str(step.arguments.get('connector_id','')).lower()!=expected_connector:
                    errors.append({'step_id':step.step_id,'tool':step.preferred_tool,'error':'target_connector_mismatch','expected_connector':expected_connector})
            error=self._schema_argument_error(step,schemas)
            if error:
                errors.append({'step_id':step.step_id,'tool':step.preferred_tool,**error})
        if errors:
            raise PlanValidationError('invalid_tool_arguments:'+json.dumps(errors,sort_keys=True,separators=(',',':')))

    def _block_invalid_arguments(self,goal,plan,run,step,error):
        """Terminal fail-closed handling for malformed persisted/executable steps."""
        error=dict(error)
        step.result={'output':error,'verification':{'verified':False,'method':'required-argument/schema guard','reason':error.get('error','invalid_arguments')}}
        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED'
        self.store.event(goal.goal_id,'tool_arguments_rejected',{'step_id':step.step_id,'tool':step.preferred_tool,**error},now())
        self.traces.record('validation',step.preferred_tool,'BLOCKED',goal_id=goal.goal_id,task_run_id=run.task_run_id,trace_id=run.trace_id,correlation={'step_id':step.step_id},detail=error)
        self._persist(goal,plan,run)
        return self.report(goal,plan,run)
    def start(self,request,*,user_id='user',target_device_id=None,target_device_kind=None):
        if not isinstance(request,str) or not request.strip():raise ValueError('request is required')
        if not isinstance(user_id,str) or not user_id.strip() or len(user_id)>256:raise ValueError('user_id is invalid')
        trace_id=uuid.uuid4().hex;target_device_id=str(target_device_id).strip() if target_device_id else None;target_device_kind=str(target_device_kind).strip().lower() if target_device_kind else None
        if target_device_id and len(target_device_id)>256:raise ValueError('target_device_id is invalid')
        if target_device_kind and target_device_kind not in {'computer','linux','mobile'}:raise ValueError('target_device_kind is invalid')
        goal=self._goal(request,user_id,target_device_id,target_device_kind);self.store.save_goal(goal);self.store.event(goal.goal_id,'goal_created',{'user_id':user_id,'target_device_kind':target_device_kind},now());self.traces.record('goal','personal_agent','CREATED',goal_id=goal.goal_id,trace_id=trace_id,correlation={'user_id':user_id})
        goal.status=GoalStatus.UNDERSTANDING;goal.updated_at=now();self.store.save_goal(goal)
        context=None
        if self.context_provider is not None:
            try:
                try:richer=self.context_provider.gather(request,owner_user_id=goal.user_id,optimized=True)
                except TypeError:richer=self.context_provider.gather(request)
                context={'source':'gen2-personal-context','rendered':str(richer.get('items',[]))[:6000],'item_count':richer.get('item_count',0)}
            except Exception as exc:
                self.store.event(goal.goal_id,'context_provider_failed',{'error_type':type(exc).__name__},now())
        if context is None:
            context=self.gen1.retrieve_context(request,goal.context_requirements)
        if self.documents is not None:
            try:
                docctx=self.documents.context(request,user_id=user_id,k=5,max_chars=5000)
                if docctx.get('item_count'):
                    context={'source':'documents+'+str(context.get('source','')),'rendered':('DOCUMENT_EVIDENCE:\n'+docctx['rendered']+'\nOTHER_CONTEXT:\n'+str(context.get('rendered','')))[:10000],'document_items':docctx['items']}
                    self.store.event(goal.goal_id,'document_context_retrieved',{'item_count':docctx['item_count'],'document_ids':sorted({x['provenance']['document_id'] for x in docctx['items']})},now())
            except Exception as exc:self.store.event(goal.goal_id,'document_context_failed',{'error_type':type(exc).__name__},now())
        remembered=self.memory.recall(request,owner_user_id=user_id,limit=5)
        if remembered:context={'source':'completion_memory+'+str(context.get('source','')),'rendered':(str(remembered)+'\n'+str(context.get('rendered','')))[:6000]}
        health=self._execution_health();capabilities=list(health.get('tools',[]))
        schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name') in capabilities}
        minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'tool_schemas':schemas,'deadline':goal.deadline,'constraints':goal.constraints}
        self.store.event(goal.goal_id,'context_retrieved',{'source':minimal['source'],'capability_count':len(capabilities)},now());self.traces.record('context','personal_context','RETRIEVED',goal_id=goal.goal_id,trace_id=trace_id,detail={'source':minimal['source'],'capability_count':len(capabilities)})
        last_error=None
        for attempt in range(self.planner_retries+1):
            try:
                proposal,provenance=self.planner.propose(goal,minimal,capabilities)
                validator=PlanValidator(set(capabilities),self.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
                self._validate_plan_arguments(plan,schemas,goal)
                self.store.save_plan_proposal(proposal);self.store.save_provenance(goal.goal_id,provenance)
                for permission,risk in decisions:self.store.save_permission(goal.goal_id,permission);self.store.save_risk(goal.goal_id,risk)
                break
            except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                last_error=exc;self.store.event(goal.goal_id,'planning_failed',{'attempt':attempt+1,'error_type':type(exc).__name__,'reason':str(exc)[:200]},now());self.traces.record('planning','planner','FAILED',goal_id=goal.goal_id,trace_id=trace_id,detail={'attempt':attempt+1,'error_type':type(exc).__name__})
        else:
            goal.status=GoalStatus.BLOCKED if isinstance(last_error,PlanValidationError) else GoalStatus.WAITING;goal.updated_at=now();self.store.save_goal(goal)
            return {'goal_id':goal.goal_id,'trace_id':trace_id,'status':goal.status.value,'text':f'Planning could not produce a safe executable plan: {last_error}. No tools were executed.','checked':[],'verified':[],'approvals':[]}
        goal.plan_id=plan.plan_id;goal.success_criteria=[c['description'] for c in proposal.success_criteria];goal.status=GoalStatus.PLANNED;goal.updated_at=now();self.store.save_plan(plan);self.store.save_goal(goal)
        criteria=list(proposal.success_criteria)
        criteria.extend([
            {'description':'Validated execution plan persisted','verification_method':'plan_persisted'},
            {'description':'All executable steps independently verified','verification_method':'all_steps_verified'},
        ])
        seen=set()
        for c in criteria:
            key=(c['description'],c['verification_method'])
            if key in seen:continue
            seen.add(key);self.store.save_criterion(GoalSuccessCriterion(uuid.uuid4().hex,goal.goal_id,c['description'],c['verification_method'],CriterionStatus.PENDING,{}))
        self.store.event(goal.goal_id,'plan_validated',{'plan_id':plan.plan_id,'proposal_id':proposal.proposal_id},now());self.traces.record('planning','planner','VALIDATED',goal_id=goal.goal_id,trace_id=trace_id,detail={'plan_id':plan.plan_id})
        run=TaskRun(uuid.uuid4().hex,goal.goal_id,None,[],[],[s.step_id for s in plan.steps],[],[],[],now(),now(),goal.deadline,'RUNNING',trace_id);self.store.save_task_run(run);self.traces.record('task','personal_agent','STARTED',goal_id=goal.goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'plan_id':plan.plan_id})
        return self.resume(goal.goal_id)
    def _replan_attempts(self,goal_id):return sum(1 for e in self.store.events(goal_id) if e['event_type']=='replan_attempted')
    def replan(self,goal_id):
        goal=self.store.load_goal(goal_id);old_plan=self.store.load_plan(goal.plan_id);old_run=self.store.load_task_run_for_goal(goal_id);trace_id=old_run.trace_id or uuid.uuid4().hex
        if goal.status not in {GoalStatus.WAITING,GoalStatus.BLOCKED,GoalStatus.FAILED}:raise ValueError('goal is not eligible for replanning')
        if any(a.status==ApprovalStatus.PENDING for a in self.store.approvals_for_goal(goal_id)):raise ValueError('pending approvals must be resolved before replanning')
        attempt=self._replan_attempts(goal_id)+1;self.store.event(goal_id,'replan_attempted',{'attempt':attempt},now());self.traces.record('recovery','personal_agent','REPLAN_STARTED',goal_id=goal_id,task_run_id=old_run.task_run_id,trace_id=trace_id,detail={'attempt':attempt})
        context=self.gen1.retrieve_context(goal.user_request,goal.context_requirements)
        if self.context_provider is not None:
            try:
                richer=self.context_provider.gather(goal.user_request);context={'source':'gen2-personal-context','rendered':str(richer.get('items',[]))[:6000],'item_count':richer.get('item_count',0)}
            except Exception as exc:self.store.event(goal.goal_id,'context_provider_failed',{'error_type':type(exc).__name__},now())
        if self.documents is not None:
            try:
                docctx=self.documents.context(goal.user_request,user_id=goal.user_id,k=5,max_chars=5000)
                if docctx.get('item_count'):context={'source':'documents+'+str(context.get('source','')),'rendered':('DOCUMENT_EVIDENCE:\n'+docctx['rendered']+'\nOTHER_CONTEXT:\n'+str(context.get('rendered','')))[:10000],'document_items':docctx['items']}
            except Exception as exc:self.store.event(goal.goal_id,'document_context_failed',{'error_type':type(exc).__name__},now())
        health=self._execution_health();capabilities=list(health.get('tools',[]));schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name') in capabilities};minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'tool_schemas':schemas,'deadline':goal.deadline,'constraints':goal.constraints}
        proposal,provenance=self.planner.propose(goal,minimal,capabilities);validator=PlanValidator(set(capabilities),self.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
        self._validate_plan_arguments(plan,schemas,goal)
        self.store.save_plan_proposal(proposal);self.store.save_provenance(goal_id,provenance)
        for permission,risk in decisions:self.store.save_permission(goal_id,permission);self.store.save_risk(goal_id,risk)
        old_run.status='SUPERSEDED';old_run.updated_at=now();self.store.save_task_run(old_run);self.store.clear_criteria(goal_id)
        goal.plan_id=plan.plan_id;goal.success_criteria=[c['description'] for c in proposal.success_criteria];goal.status=GoalStatus.PLANNED;self.store.save_plan(plan)
        criteria=list(proposal.success_criteria)+[{'description':'Validated execution plan persisted','verification_method':'plan_persisted'},{'description':'All executable steps independently verified','verification_method':'all_steps_verified'}]
        seen=set()
        for c in criteria:
            key=(c['description'],c['verification_method'])
            if key in seen:continue
            seen.add(key);self.store.save_criterion(GoalSuccessCriterion(uuid.uuid4().hex,goal_id,c['description'],c['verification_method'],CriterionStatus.PENDING,{}))
        run=TaskRun(uuid.uuid4().hex,goal_id,None,[],[],[x.step_id for x in plan.steps],[],[],[],now(),now(),goal.deadline,'RUNNING',trace_id);self.store.save_task_run(run);self.store.save_goal(goal);self.store.event(goal_id,'replanned',{'old_plan_id':old_plan.plan_id,'new_plan_id':plan.plan_id},now());self.traces.record('planning','planner','REPLANNED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,detail={'plan_id':plan.plan_id})
        return self.resume(goal_id)
    def continue_goal(self,goal_id,instruction):
        if not isinstance(instruction,str) or not instruction.strip():raise ValueError('continuation instruction required')
        goal=self.store.load_goal(goal_id)
        if any(a.status==ApprovalStatus.PENDING for a in self.store.approvals_for_goal(goal_id)):raise ValueError('pending approvals must be resolved before continuation')
        original=goal.user_request;goal.user_request=(original+'\nContinuation: '+instruction.strip())[:12000];goal.status=GoalStatus.WAITING;self.store.save_goal(goal);self.store.event(goal_id,'goal_continuation_requested',{'previous_status':'COMPLETED' if self.store.load_task_run_for_goal(goal_id).status=='COMPLETED' else 'NONTERMINAL'},now())
        try:return self.replan(goal_id)
        except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
            goal=self.store.load_goal(goal_id);goal.status=GoalStatus.WAITING;self.store.save_goal(goal);self.store.event(goal_id,'continuation_planning_failed',{'error_type':type(exc).__name__},now())
            run=self.store.load_task_run_for_goal(goal_id);return {'goal_id':goal_id,'task_run_id':run.task_run_id,'trace_id':run.trace_id,'status':'WAITING','text':f'Continuation is saved, but planning is unavailable: {exc}. No tools were executed.','checked':[],'verified':[],'approvals':[],'gen1_approvals':[],'model_provenance':self.store.provenance_for_goal(goal_id),'criteria':[c.to_dict() for c in self.store.criteria_for_goal(goal_id)]}

    def _approval_for(self,goal_id,step_id):
        items=[a for a in self.store.approvals_for_goal(goal_id) if a.step_id==step_id and a.status in {ApprovalStatus.PENDING,ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}]
        return items[-1] if items else None
    @staticmethod
    def _contains_model_authority(value):
        forbidden={'approved','approval_id','grant_id','authorization_override'}
        if isinstance(value,dict):
            return bool(forbidden.intersection(value)) or any(PersonalAgent._contains_model_authority(v) for v in value.values())
        if isinstance(value,(list,tuple)):
            return any(PersonalAgent._contains_model_authority(v) for v in value)
        return False
    @staticmethod
    def _exact_approval_scope(goal,step):
        return json.dumps({'user_id':goal.user_id,'goal_id':goal.goal_id,'tool':step.preferred_tool,'arguments':step.arguments},sort_keys=True,separators=(',',':'),ensure_ascii=False)
    def _workspace_test_execution_grant(self,goal,run,step,approval,scope):
        if approval is None or approval.status!=ApprovalStatus.APPROVED:raise PermissionError('workspace_test requires approved human authorization')
        actor=str(approval.approved_by or '').strip()
        if not actor or actor.lower() in {'model','assistant','nemotron','system','system_cancel'}:raise PermissionError('workspace_test requires trusted human approval')
        center=PermissionCenter(self.store,goal.goal_id)
        existing=[p for p in center.list(include_inactive=True) if p.capability=='workspace_test' and p.metadata.get('approval_id')==approval.approval_id]
        if existing:
            grant=existing[-1]
            if grant.subject!=goal.user_id or grant.scope!=scope or grant.metadata.get('task_run_id')!=run.task_run_id or grant.metadata.get('step_id')!=step.step_id:raise PermissionError('workspace_test execution grant scope mismatch')
            if grant.status!=PermissionStatus.ACTIVE:raise PermissionError('workspace_test execution grant is not active')
            return center,grant
        expires=(datetime.now(UTC)+timedelta(minutes=5)).isoformat()
        if approval.expires_at:
            try:
                approved_expiry=datetime.fromisoformat(str(approval.expires_at).replace('Z','+00:00'));approved_expiry=approved_expiry if approved_expiry.tzinfo else approved_expiry.replace(tzinfo=UTC);expires=min(datetime.fromisoformat(expires),approved_expiry).isoformat()
            except (TypeError,ValueError):raise PermissionError('workspace_test approval expiry invalid')
        grant=center.grant(goal.user_id,'workspace_test',scope,PermissionEffect.ALLOW,granted_by=actor,expires_at=expires,metadata={'approval_id':approval.approval_id,'task_run_id':run.task_run_id,'step_id':step.step_id,'one_time':True})
        self.store.event(goal.goal_id,'workspace_test_grant_issued',{'permission_id':grant.permission_id,'approval_id':approval.approval_id,'step_id':step.step_id,'expires_at':grant.expires_at},now());self.traces.record('authorization','workspace_test_grant','ISSUED',goal_id=goal.goal_id,task_run_id=run.task_run_id,trace_id=run.trace_id,correlation={'approval_id':approval.approval_id,'permission_id':grant.permission_id,'step_id':step.step_id},detail={'one_time':True})
        return center,grant
    def decide_approval(self,approval_id:str,decision:str,*,actor:str='user'):
        approval=self.store.load_approval(approval_id)
        if approval.status!=ApprovalStatus.PENDING:raise ValueError('approval is not pending')
        if approval.capability=='workspace_test' and decision=='approve' and str(actor).strip().lower() in {'model','assistant','nemotron','system','system_cancel'}:raise PermissionError('model_cannot_approve_workspace_test')
        if approval.expires_at and self._deadline_expired(approval.expires_at):
            approval.status=ApprovalStatus.EXPIRED;approval.decision_at=now();self.store.save_approval(approval);self.store.event(approval.goal_id,'approval_expired',{'approval_id':approval_id},now());raise ValueError('approval has expired')
        if decision not in {'approve','reject'}:raise ValueError('decision must be approve or reject')
        approval.status=ApprovalStatus.APPROVED if decision=='approve' else ApprovalStatus.REJECTED;approval.approved_by=actor;approval.decision_at=now();self.store.save_approval(approval)
        self.store.event(approval.goal_id,'approval_decided',{'approval_id':approval_id,'status':approval.status.value,'actor':actor},now());return approval.to_dict()
    def _deadline_expired(self,deadline):
        if not deadline:return False
        try:
            value=datetime.fromisoformat(deadline.replace('Z','+00:00'))
            if value.tzinfo is None:value=value.replace(tzinfo=UTC)
            return value<=datetime.now(UTC)
        except (TypeError,ValueError):return True
    def cancel(self,goal_id):
        goal=self.store.load_goal(goal_id);plan=self.store.load_plan(goal.plan_id);run=self.store.load_task_run_for_goal(goal_id)
        if goal.status==GoalStatus.COMPLETED:raise ValueError('completed goal cannot be cancelled')
        goal.status=GoalStatus.CANCELLED;run.status='CANCELLED';run.current_step=None;self.store.cancel_pending_approvals(goal_id,now())
        for row in self.store.delegations(goal_id=goal_id):self.delegation.cancel(row['request']['request_id'])
        self.store.event(goal_id,'goal_cancelled',{},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
    def resume(self,goal_id):
        goal=self.store.load_goal(goal_id);plan=self.store.load_plan(goal.plan_id);run=self.store.load_task_run_for_goal(goal_id)
        if not run.trace_id:run.trace_id=uuid.uuid4().hex;self.store.save_task_run(run)
        trace_id=run.trace_id
        if goal.status==GoalStatus.COMPLETED:
            self._analyze_completion_memory(goal,run);return self.report(goal,plan,run)
        if goal.status==GoalStatus.CANCELLED:return self.report(goal,plan,run)
        if self._deadline_expired(goal.deadline):
            goal.status=GoalStatus.BLOCKED;run.status='DEADLINE_EXPIRED';self.store.event(goal_id,'deadline_expired',{'deadline':goal.deadline},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
        health=self._execution_health();schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name')}
        iterations=0
        for step in plan.steps:
            if step.status==StepStatus.VERIFIED:continue
            argument_error=self._schema_argument_error(step,schemas)
            if argument_error:
                return self._block_invalid_arguments(goal,plan,run,step,argument_error)
            if step.status==StepStatus.WAITING and run.status=='WAITING_FOR_DELEGATION_APPROVAL':
                output=(step.result or {}).get('output',{});request_id=output.get('request_id') if isinstance(output,dict) else None
                if not request_id:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                result=self.delegation.reconcile(request_id)
                if result is not None:step.result={'output':result.to_dict(),'verification':dict(result.verification)}
                self.store.event(goal_id,'delegation_approval_reconciled',{'request_id':request_id,'status':None if result is None else result.status,'verified':False if result is None else bool(result.verification.get('verified'))},now())
                if result is not None and result.status=='COMPLETED' and result.verification.get('verified') is True:
                    step.status=StepStatus.VERIFIED
                    if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                    run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];run.status='RUNNING';self.traces.record('verification','specialist_delegate','VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'method':'delegated_gen1_approval_reconciliation'});self._persist(goal,plan,run);continue
                if result is not None and result.status in {'FAILED','BLOCKED','CANCELLED'}:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                goal.status=GoalStatus.WAITING;self._persist(goal,plan,run);return self.report(goal,plan,run)
            if step.status==StepStatus.WAITING and run.status=='WAITING_FOR_GEN1_APPROVAL':
                output=(step.result or {}).get('output',{});approval_id=output.get('proposal_id') if isinstance(output,dict) else None
                status_fn=getattr(self.gen1,'approval_status',None)
                if approval_id and callable(status_fn):
                    state=status_fn(approval_id,step.preferred_tool);status=state.get('status')
                    self.store.event(goal_id,'gen1_approval_reconciled',{'approval_id':approval_id,'status':status,'verified':bool(state.get('verified'))},now())
                    if status=='APPROVED' and state.get('verified'):
                        step.status=StepStatus.VERIFIED;step.result['verification']=state
                        if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                        run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];run.status='RUNNING';self.traces.record('verification',step.preferred_tool,'VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id},detail={'method':'gen1_approval_reconciliation'});self._persist(goal,plan,run);continue
                    if status in {'REJECTED','EXPIRED','CANCELLED'}:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                    goal.status=GoalStatus.WAITING;self._persist(goal,plan,run);return self.report(goal,plan,run)
                goal.status=GoalStatus.WAITING;self._persist(goal,plan,run);return self.report(goal,plan,run)
            if any(next(x for x in plan.steps if x.step_id==d).status!=StepStatus.VERIFIED for d in step.dependencies):continue
            if iterations>=self.max_iterations:goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            iterations+=1
            if (step.preferred_tool.startswith('automation_') or step.preferred_tool in {'connector_invoke','image_generate','document_ingest','daily_brief_update','daily_brief_close','learning_plan_create','learning_assess','workspace_test'}) and any(k in step.arguments for k in {'approved','approval_id','grant_id','authorization_override'}):
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'model_authority_rejected',{'step_id':step.step_id},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            if step.preferred_tool=='workspace_test' and (set(step.arguments)!={'project_name'} or not isinstance(step.arguments.get('project_name'),str) or not step.arguments['project_name'].strip()):
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'workspace_test_scope_rejected',{'step_id':step.step_id},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            permission,risk=self.policy.evaluate(step.preferred_tool,'user',step.description,now())
            if permission.effect==PermissionEffect.DENY:
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            if permission.effect==PermissionEffect.REQUIRE_APPROVAL:
                if self._contains_model_authority(step.arguments):
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'model_authority_rejected',{'step_id':step.step_id},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
                approval=self._approval_for(goal_id,step.step_id)
                exact_scope=self._exact_approval_scope(goal,step)
                if approval is None:
                    approval=Approval(uuid.uuid4().hex,goal_id,run.task_run_id,step.step_id,step.description,step.preferred_tool,risk.level,now(),None,ApprovalStatus.PENDING,exact_scope)
                    self.store.save_approval(approval);run.approvals.append(approval.approval_id);self.store.event(goal_id,'approval_required',{'approval_id':approval.approval_id,'step_id':step.step_id},now())
                if approval.status==ApprovalStatus.PENDING and approval.expires_at and self._deadline_expired(approval.expires_at):
                    approval.status=ApprovalStatus.EXPIRED;approval.decision_at=now();self.store.save_approval(approval);self.store.event(goal_id,'approval_expired',{'approval_id':approval.approval_id},now())
                if approval.status==ApprovalStatus.PENDING:
                    step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_APPROVAL';self._persist(goal,plan,run);return self.report(goal,plan,run)
                if approval.status==ApprovalStatus.EXPIRED:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='APPROVAL_EXPIRED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                if approval.status==ApprovalStatus.REJECTED:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                if approval.status==ApprovalStatus.APPROVED and approval.requested_scope!=exact_scope:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED'
                    event_type='automation_approval_scope_mismatch' if step.preferred_tool.startswith('automation_') else 'approval_scope_mismatch'
                    self.store.event(goal_id,event_type,{'approval_id':approval.approval_id,'step_id':step.step_id,'tool':step.preferred_tool},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            delegation_request=None;request_id=None;specialists=[]
            if step.preferred_tool=='specialist_delegate':
                args=dict(step.arguments);specialists=list(args.get('specialists',[]));objective=str(args.get('objective') or step.description);authorized_action=args.get('authorized_action');request_id=self.delegation.deterministic_id(goal_id,run.task_run_id,step.step_id,specialists,objective,authorized_action);inputs=dict(args.get('inputs',{}))
                if step.dependencies:
                    dependency_results={}
                    for dep_id in step.dependencies:
                        dep=next(x for x in plan.steps if x.step_id==dep_id);value=(dep.result or {}).get('output')
                        if isinstance(value,dict):dependency_results[dep_id]={'findings':str(value.get('findings',''))[:2000],'evidence':list(value.get('evidence',[]))[:20],'verification':dict((dep.result or {}).get('verification',{}))}
                    if dependency_results:inputs['verified_dependency_results']=dependency_results
                trusted_scope={}
                if isinstance(authorized_action,dict) and authorized_action.get('tool')=='workspace_package':
                    fn=getattr(self.gen1,'package_source_identity',None)
                    if not callable(fn):
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'delegation_package_source_unavailable',{},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
                    try:trusted_scope={'package_source':fn(str((authorized_action.get('arguments') or {}).get('project_name','')))}
                    except Exception as exc:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'delegation_package_source_invalid',{'error_type':type(exc).__name__},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
                delegation_request=DelegationRequest(request_id,goal_id,run.task_run_id,trace_id,goal.user_id,str(args.get('capability','reasoning')),specialists,objective,inputs,list(args.get('constraints',goal.constraints)),goal.deadline,step.risk,list(args.get('required_evidence',step.success_criteria)),now(),authorized_action,None,trusted_scope)
                try:
                    record=self.delegation.prepare(delegation_request);delegation_request=record.request;self.store.event(goal_id,'delegation_prepared',{'request_id':request_id,'specialists':specialists},now());self.traces.record('delegation','gen1_run_multi','PREPARED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists,'user_id':goal.user_id});self._persist(goal,plan,run)
                    if delegation_request.authorized_action is not None and not delegation_request.grant_id:
                        approval=self._approval_for(goal_id,step.step_id);scope=self.delegation.grants.approval_scope(delegation_request);tool=str(delegation_request.authorized_action.get('tool'));_,write_risk=self.policy.evaluate(tool,'user',scope,now())
                        if approval is None:
                            approval=Approval(uuid.uuid4().hex,goal_id,run.task_run_id,step.step_id,f'Authorize {specialists[0]} specialist to use {tool}', 'specialist_delegate',write_risk.level,now(),(datetime.now(UTC)+timedelta(minutes=15)).isoformat(),ApprovalStatus.PENDING,scope)
                            self.store.save_approval(approval);run.approvals.append(approval.approval_id);self.store.event(goal_id,'delegation_grant_approval_required',{'approval_id':approval.approval_id,'request_id':request_id,'specialist':specialists[0],'tool':tool},now());self.traces.record('authorization','delegation_grant','APPROVAL_REQUIRED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'request_id':request_id},detail={'specialist':specialists[0],'tool':tool})
                        if approval.status==ApprovalStatus.PENDING and approval.expires_at and self._deadline_expired(approval.expires_at):
                            approval.status=ApprovalStatus.EXPIRED;approval.decision_at=now();self.store.save_approval(approval)
                        if approval.status==ApprovalStatus.PENDING:
                            step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_APPROVAL';self._persist(goal,plan,run);return self.report(goal,plan,run)
                        if approval.status in {ApprovalStatus.REJECTED,ApprovalStatus.EXPIRED,ApprovalStatus.CANCELLED}:
                            step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                        grant=self.delegation.grants.issue(delegation_request,approval);record=self.delegation.attach_grant(request_id,grant.grant_id);delegation_request=record.request;self.store.event(goal_id,'delegation_grant_issued',{'grant_id':grant.grant_id,'approval_id':approval.approval_id,'request_id':request_id,'specialist':specialists[0],'tool':grant.capability,'expires_at':grant.expires_at},now());self.traces.record('authorization','delegation_grant','ISSUED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'grant_id':grant.grant_id,'request_id':request_id},detail={'specialist':specialists[0],'tool':grant.capability,'issuer':grant.issuer,'expires_at':grant.expires_at})
                except Exception as exc:
                    output={'status':'FAILED','request_id':request_id,'failure':{'category':type(exc).__name__,'reason':str(exc)[:300]}};obs=ToolObservation(False,step.preferred_tool,output,{'verified':False,'method':'delegation validation/authorization failed'})
                    step.result={'output':obs.output,'verification':obs.verification};self.store.event(goal_id,'delegation_observed',{'request_id':request_id,'status':'FAILED','specialists':specialists},now());self.traces.record('delegation','gen1_run_multi','FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists});step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
            if step.attempts>step.retry_limit:
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            goal.status=GoalStatus.EXECUTING;step.status=StepStatus.EXECUTING;step.attempts+=1;run.current_step=step.step_id;self._persist(goal,plan,run);self.traces.record('action',step.preferred_tool,'STARTED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
            if step.preferred_tool=='specialist_delegate':
                result=self.delegation.execute(delegation_request);output=result.to_dict();obs=ToolObservation(result.status=='COMPLETED',step.preferred_tool,output,dict(result.verification))
                if delegation_request.grant_id:
                    try:
                        consumed=self.delegation.grants.load(delegation_request.grant_id)
                        if consumed.state=='CONSUMED':
                            self.store.event(goal_id,'delegation_grant_consumed',{'grant_id':consumed.grant_id,'approval_id':consumed.approval_id,'request_id':request_id,'specialist':consumed.allowed_specialists[0],'tool':consumed.capability,'consumed_at':consumed.consumed_at},now());self.traces.record('authorization','delegation_grant','CONSUMED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':consumed.approval_id,'grant_id':consumed.grant_id,'request_id':request_id},detail={'specialist':consumed.allowed_specialists[0],'tool':consumed.capability,'issuer':consumed.issuer})
                    except Exception:pass
                self.store.event(goal_id,'delegation_observed',{'request_id':request_id,'status':output.get('status'),'specialists':specialists},now());self.traces.record('delegation','gen1_run_multi',str(output.get('status','FAILED')),goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists,'grant_id':delegation_request.grant_id})
                if result.status=='WAITING_APPROVAL':
                    step.result={'output':obs.output,'verification':obs.verification};step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_DELEGATION_APPROVAL'
                    for pending_item in result.provenance.get('pending_approvals',[]):
                        aid=pending_item.get('approval_id')
                        if isinstance(aid,str) and aid not in run.approvals:run.approvals.append(aid)
                    self.store.event(goal_id,'delegated_gen1_approval_required',{'request_id':request_id,'approvals':result.provenance.get('pending_approvals',[])},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            elif step.preferred_tool in {'learning_plan_create','learning_plan_inspect','learning_assess'} and self.learning is not None:
                value=self.learning.invoke(step.preferred_tool,step.arguments,owner_user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
                self.store.event(goal_id,'learning_state_updated' if step.preferred_tool!='learning_plan_inspect' else 'learning_state_inspected',{'tool':step.preferred_tool,'plan_id':value['verification'].get('plan_id'),'assessment_id':value['verification'].get('assessment_id')},now())
            elif step.preferred_tool.startswith('automation_') and self.automation is not None and step.preferred_tool!='automation_inspect':
                value=self.automation.invoke(step.preferred_tool,step.arguments,owner_user_id=goal.user_id,source_goal_id=goal.goal_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            elif step.preferred_tool=='connector_list' and self.connectors is not None:
                value={'connectors':self.connectors.discover(owner_user_id=goal.user_id)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':all(x.get('connector_id') for x in value['connectors']),'method':'owner-scoped persisted connector registry projection'})
            elif step.preferred_tool=='connector_inspect' and self.connectors is not None:
                cid=str(step.arguments.get('connector_id',''))
                if not cid:
                    return self._block_invalid_arguments(goal,plan,run,step,{'error':'missing_required_argument','argument':'connector_id'})
                else:
                    value=self.connectors.inspect(cid,owner_user_id=goal.user_id);obs=ToolObservation(value.get('connector_id')==cid,step.preferred_tool,value,{'verified':value.get('connector_id')==cid and value.get('owner_user_id',goal.user_id)==goal.user_id,'method':'owner-scoped connector state reread','connector_id':cid})
            elif step.preferred_tool=='connector_capabilities' and self.connectors is not None:
                cid=str(step.arguments.get('connector_id',''))
                if not cid:
                    return self._block_invalid_arguments(goal,plan,run,step,{'error':'missing_required_argument','argument':'connector_id'})
                else:
                    value={'connector_id':cid,'capabilities':self.connectors.capabilities(cid)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':bool(value['capabilities']),'method':'typed connector descriptor reread','connector_id':cid})
            elif step.preferred_tool=='connector_health' and self.connectors is not None:
                cid=str(step.arguments.get('connector_id',''))
                if not cid:
                    return self._block_invalid_arguments(goal,plan,run,step,{'error':'missing_required_argument','argument':'connector_id'})
                else:
                    value=self.connectors.health(cid,owner_user_id=goal.user_id);obs=ToolObservation(True,step.preferred_tool,value,{'verified':value.get('connector_id')==cid and value.get('owner_user_id')==goal.user_id,'method':'connector adapter health recheck or explicit unavailable state','connector_id':cid})
            elif step.preferred_tool in {'connector_read','connector_invoke'} and self.connectors is not None:
                cid=str(step.arguments.get('connector_id',''));op=str(step.arguments.get('operation',''));args=dict(step.arguments.get('arguments') or {});classification=str(step.arguments.get('classification','PRIVATE'));device_id=step.arguments.get('device_id');approval=self._approval_for(goal_id,step.step_id) if step.preferred_tool=='connector_invoke' else None
                try:
                    fn=self.connectors.invoke_read if step.preferred_tool=='connector_read' else self.connectors.invoke
                    value=fn(cid,op,args,owner_user_id=goal.user_id,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,classification=classification,approval=approval,device_id=device_id);verified=bool((value.get('verification') or {}).get('verified'));obs=ToolObservation(verified,step.preferred_tool,value,value.get('verification') or {'verified':False,'reason':'connector_verification_missing'})
                    self.store.event(goal_id,'connector_invoked',{'connector_id':cid,'operation':op,'request_id':value.get('request_id'),'status':value.get('status'),'verified':verified},now());self.traces.record('connector',cid,str(value.get('status','FAILED')),goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':value.get('request_id')},detail={'operation':op,'verified':verified,'read_only':step.preferred_tool=='connector_read'})
                except Exception as exc:
                    obs=ToolObservation(False,step.preferred_tool,{'error':'connector_invocation_failed','error_type':type(exc).__name__},{'verified':False,'method':'connector manager policy/authorization/invocation/verification boundary','reason':str(getattr(exc,'category',type(exc).__name__))})
            elif step.preferred_tool in {'notification_inspect','notification_explain'} and self.notifications is not None:
                nid=str(step.arguments.get('notification_id',''))
                if not nid:
                    return self._block_invalid_arguments(goal,plan,run,step,{'error':'missing_required_argument','argument':'notification_id'})
                else:
                    value=self.notifications.inspect(nid,owner_user_id=goal.user_id) if step.preferred_tool=='notification_inspect' else self.notifications.explain(nid,owner_user_id=goal.user_id);obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped notification intelligence reread','notification_id':nid})
            elif step.preferred_tool=='notification_delivery_inspect' and self.notification_delivery is not None:
                value=self.notification_delivery.inspect(owner_user_id=goal.user_id,notification_id=step.arguments.get('notification_id'),attempt_id=step.arguments.get('attempt_id'));obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped delivery state reread'})
            elif step.preferred_tool=='notification_channels_inspect' and self.notification_delivery is not None:
                value={'channels':self.notification_delivery.channel_states(goal.user_id)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped channel state reread'})
            elif step.preferred_tool=='notification_delivery_retry' and self.notification_delivery is not None:
                attempt_id=str(step.arguments.get('attempt_id',''));value=self.notification_delivery.retry(attempt_id,owner_user_id=goal.user_id);reread=self.store.notification_delivery_attempt(value['attempt_id']);verified=bool(reread and reread.get('notification_id')==value.get('notification_id'));obs=ToolObservation(verified,step.preferred_tool,reread or value,{'verified':verified,'method':'authorized retry + persisted delivery reread','attempt_id':value.get('attempt_id')})
            elif step.preferred_tool=='notification_acknowledge' and self.notification_delivery is not None:
                attempt_id=str(step.arguments.get('attempt_id',''));value=self.notification_delivery.acknowledge(attempt_id,owner_user_id=goal.user_id);reread=self.store.notification_delivery_attempt(attempt_id);verified=bool(reread and reread.get('status')=='ACKNOWLEDGED');obs=ToolObservation(verified,step.preferred_tool,reread or value,{'verified':verified,'method':'authorized acknowledgement + persisted delivery reread','attempt_id':attempt_id})
            elif step.preferred_tool=='operations_snapshot' and self.operations is not None:
                value=self.operations.invoke(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            elif step.preferred_tool.startswith('daily_brief_') and self.daily_os is not None:
                value=self.daily_os.invoke(step.preferred_tool,step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            elif step.preferred_tool=='perception_observe' and self.perception is not None:
                robot_id=str(step.arguments.get('robot_id',''));value=self.perception.observe(robot_id);oid=value.get('observation',{}).get('observation_id');freshness=value.get('freshness',{}).get('state');verified=value.get('status')=='OBSERVED' and freshness=='FRESH' and value.get('fusion',{}).get('status')=='CURRENT';obs=ToolObservation(verified,step.preferred_tool,value,{'verified':verified,'method':'normalized perception + persisted observation + freshness/fusion check','observation_id':oid,'robot_id':robot_id,'freshness':freshness})
                if oid:
                    self.store.event(goal_id,'perception_observed',{'observation_id':oid,'robot_id':robot_id,'freshness':freshness,'source':value.get('observation',{}).get('source')},now());self.traces.record('perception','perception_observe','OBSERVED' if verified else 'UNVERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'observation_id':oid,'robot_id':robot_id},detail={'freshness':freshness,'source':value.get('observation',{}).get('source')})
            elif step.preferred_tool=='ros2_sim_move' and self.perception is not None:
                try:self.perception.require_fresh('turtle1')
                except Exception as exc:obs=ToolObservation(False,step.preferred_tool,{'error':'fresh perception required before simulated movement','error_type':type(exc).__name__},{'verified':False,'reason':'fresh_perception_required'})
                else:obs=self.gen1.invoke(step.preferred_tool,step.arguments)
            elif step.preferred_tool=='image_generate' and self.images is not None:
                try:
                    value=self.images.invoke(step.arguments,user_id=goal.user_id,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,step_id=step.step_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
                except Exception as exc:
                    obs=ToolObservation(False,step.preferred_tool,{'error':'image_generation_failed','error_type':type(exc).__name__},{'verified':False,'method':'image generation requires routed provider plus independently verified artifact','reason':type(exc).__name__})
                if obs.verification.get('verified') and obs.output.get('artifact_id') is not None:
                    ref='artifact:'+str(obs.output['artifact_id'])
                    if ref not in run.artifacts:run.artifacts.append(ref)
            elif step.preferred_tool=='document_ingest' and self.documents is not None:
                value=self.documents.invoke_ingest(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            elif step.preferred_tool=='document_search' and self.documents is not None:
                value=self.documents.invoke_search(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            elif step.preferred_tool=='workspace_test':
                try:
                    approval=self._approval_for(goal_id,step.step_id);scope=json.dumps({'user_id':goal.user_id,'goal_id':goal_id,'tool':'workspace_test','arguments':step.arguments},sort_keys=True,separators=(',',':'),ensure_ascii=False)
                    center,grant=self._workspace_test_execution_grant(goal,run,step,approval,scope)
                    if center.authorize(goal.user_id,'workspace_test',scope)!=PermissionEffect.ALLOW:raise PermissionError('workspace_test execution grant authorization failed')
                    center.revoke(grant.permission_id,actor='workspace_test_consumer');self.store.event(goal_id,'workspace_test_grant_consumed',{'permission_id':grant.permission_id,'approval_id':approval.approval_id,'step_id':step.step_id},now());self.traces.record('authorization','workspace_test_grant','CONSUMED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'permission_id':grant.permission_id,'step_id':step.step_id},detail={'one_time':True})
                    trusted_arguments={'project_name':str(step.arguments['project_name']),'approved':True};obs=self.gen1.invoke(step.preferred_tool,trusted_arguments)
                except Exception as exc:
                    obs=ToolObservation(False,step.preferred_tool,{'error':'workspace_test_authorization_failed','error_type':type(exc).__name__},{'verified':False,'reason':'workspace_test_execution_grant_failed'})
            else:
                obs=self.gen1.invoke(step.preferred_tool,step.arguments)
            step.result={'output':obs.output,'verification':obs.verification};self.store.event(goal_id,'tool_observed',{'tool':step.preferred_tool,'ok':obs.ok},now());self.traces.record('observation',step.preferred_tool,'OK' if obs.ok else 'FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
            if not obs.ok:
                if isinstance(obs.output,dict) and obs.output.get('error') in {'missing_required_argument','invalid_arguments','unexpected_arguments'}:
                    return self._block_invalid_arguments(goal,plan,run,step,dict(obs.output))
                step.status=StepStatus.FAILED
                if step.step_id not in run.failed_steps:run.failed_steps.append(step.step_id)
                decision=self.failures.classify(obs.output,attempts=step.attempts,retry_limit=step.retry_limit);self.store.event(goal_id,'failure_classified',decision.to_dict()|{'step_id':step.step_id},now());self.traces.record('recovery','failure_classifier',decision.action,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id},detail={'category':decision.category,'retryable':decision.retryable})
                if decision.action=='REPLAN':
                    goal.status=GoalStatus.BLOCKED;run.status='REPLAN';self._persist(goal,plan,run)
                    if self._replan_attempts(goal_id)<self.max_replans:
                        try:return self.replan(goal_id)
                        except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                            goal=self.store.load_goal(goal_id);run=self.store.load_task_run_for_goal(goal_id);goal.status=GoalStatus.BLOCKED;run.status='REPLAN_FAILED';self.store.event(goal_id,'automatic_replan_failed',{'error_type':type(exc).__name__},now());self.traces.record('recovery','personal_agent','REPLAN_FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=run.trace_id or trace_id,detail={'error_type':type(exc).__name__});self._persist(goal,plan,run);return self.report(goal,plan,run)
                    return self.report(goal,plan,run)
                goal.status=GoalStatus.WAITING if decision.action in {'RETRY','WAIT_USER','WAIT_EXTERNAL'} else GoalStatus.BLOCKED;run.status=decision.action;self._persist(goal,plan,run);return self.report(goal,plan,run)
            goal.status=GoalStatus.VERIFYING
            if not obs.verification.get('verified'):
                step.status=StepStatus.FAILED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'verification_failed',obs.verification,now());self.traces.record('verification',step.preferred_tool,'FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id});self._persist(goal,plan,run);return self.report(goal,plan,run)
            if obs.requires_approval:
                step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_GEN1_APPROVAL'
                if obs.approval_id and obs.approval_id not in run.approvals:run.approvals.append(obs.approval_id)
                self.store.event(goal_id,'gen1_approval_required',{'approval_id':obs.approval_id,'tool':step.preferred_tool},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            step.status=StepStatus.VERIFIED
            if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
            run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];self.store.event(goal_id,'step_verified',{'step_id':step.step_id},now());self.traces.record('verification',step.preferred_tool,'VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
        self._evaluate_goal(goal,plan)
        if all(c.status==CriterionStatus.SATISFIED for c in self.store.criteria_for_goal(goal_id)) and all(s.status==StepStatus.VERIFIED for s in plan.steps):
            goal.status=GoalStatus.COMPLETED;run.status='COMPLETED';run.current_step=None;self.store.event(goal_id,'goal_completed',{'authority':'deterministic_goal_evaluator'},now());self.traces.record('goal','deterministic_goal_evaluator','COMPLETED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id)
        elif goal.status not in {GoalStatus.BLOCKED,GoalStatus.WAITING}:goal.status=GoalStatus.WAITING;run.status='WAITING'
        self._persist(goal,plan,run)
        if goal.status==GoalStatus.COMPLETED:self._analyze_completion_memory(goal,run)
        return self.report(goal,plan,run)
    def _analyze_completion_memory(self,goal,run):
        before={c.candidate_id for c in self.memory.list(goal.goal_id)};items=self.memory.analyze_completion(goal,run,self.store.criteria_for_goal(goal.goal_id))
        for candidate in items:
            if candidate.candidate_id in before:continue
            self.store.event(goal.goal_id,'memory_candidate_proposed',{'candidate_id':candidate.candidate_id,'category':candidate.category,'privacy':candidate.privacy_classification},now());self.traces.record('memory','completion_memory','PROPOSED',goal_id=goal.goal_id,task_run_id=run.task_run_id,trace_id=run.trace_id,correlation={'candidate_id':candidate.candidate_id},detail={'category':candidate.category,'privacy':candidate.privacy_classification})
        return items
    def memory_candidates(self,goal_id=None):return [c.to_dict() for c in self.memory.list(goal_id)]
    def decide_memory_candidate(self,candidate_id,decision,*,actor='user'):
        candidate=self.memory.decide(candidate_id,decision,actor=actor);self.store.event(candidate.goal_id,'memory_candidate_decided',{'candidate_id':candidate.candidate_id,'state':candidate.state,'actor':actor},now());self.traces.record('memory','completion_memory',candidate.state,goal_id=candidate.goal_id,task_run_id=candidate.task_run_id,trace_id=candidate.trace_id,correlation={'candidate_id':candidate.candidate_id});return candidate.to_dict()
    def reconcile_memory_candidate(self,candidate_id):
        before=self.memory.get(candidate_id);candidate=self.memory.reconcile(candidate_id)
        if candidate.state!=before.state:
            self.store.event(candidate.goal_id,'memory_candidate_reconciled',{'candidate_id':candidate.candidate_id,'state':candidate.state,'memory_id':candidate.memory_id},now());self.traces.record('memory','gen1_memory_review',candidate.state,goal_id=candidate.goal_id,task_run_id=candidate.task_run_id,trace_id=candidate.trace_id,correlation={'candidate_id':candidate.candidate_id,'memory_id':candidate.memory_id})
        return candidate.to_dict()
    def memory_candidate_for_memory(self,memory_id):
        candidate=self.memory.candidate_for_memory(memory_id);return None if candidate is None else candidate.to_dict()
    def _evaluate_goal(self,goal,plan):
        steps={s.step_id:s for s in plan.steps}
        for c in self.store.criteria_for_goal(goal.goal_id):
            if c.verification_method=='all_steps_verified':ok=all(s.status==StepStatus.VERIFIED for s in plan.steps);evidence={'verified_steps':[s.step_id for s in plan.steps if s.status==StepStatus.VERIFIED]}
            elif c.verification_method=='plan_persisted':
                try:self.store.load_plan(plan.plan_id);ok=True;evidence={'plan_id':plan.plan_id,'persisted':True}
                except KeyError:ok=False;evidence={'plan_id':plan.plan_id,'persisted':False}
            else:
                sid=c.verification_method.split(':',1)[1];ok=steps[sid].status==StepStatus.VERIFIED;evidence={'step_id':sid,'status':steps[sid].status.value}
            c.status=CriterionStatus.SATISFIED if ok else CriterionStatus.PENDING;c.evidence=evidence;self.store.save_criterion(c)
    def _persist(self,goal,plan,run):
        goal.updated_at=now();run.updated_at=now();self.store.save_plan(plan);self.store.save_goal(goal);self.store.save_task_run(run)
    def report(self,goal,plan,run):
        checked=[s.preferred_tool for s in plan.steps if s.result];verified=[s.description for s in plan.steps if s.status==StepStatus.VERIFIED]
        pending=[a for a in self.store.approvals_for_goal(goal.goal_id) if a.status==ApprovalStatus.PENDING]
        summaries=[]
        for step in plan.steps:
            if step.status!=StepStatus.VERIFIED or not isinstance(step.result,dict):continue
            output=step.result.get('output')
            if step.preferred_tool=='calculator' and isinstance(output,dict) and 'value' in output:summaries.append(f"The verified result is {output['value']}.")
            elif step.preferred_tool=='connector_list' and isinstance(output,dict):
                rows=output.get('connectors',[]);summaries.append(f"Connectors: {len(rows)} registered; "+', '.join(f"{x.get('connector_id')} {x.get('status')}" for x in rows[:6])+'.')
            elif step.preferred_tool in {'connector_inspect','connector_health'} and isinstance(output,dict):
                summaries.append(f"Connector {output.get('connector_id')} is {output.get('status',output.get('state','UNKNOWN'))}; authorization {output.get('authorization_state','unknown')}.")
            elif step.preferred_tool=='connector_capabilities' and isinstance(output,dict):
                summaries.append(f"Connector {output.get('connector_id')} exposes "+', '.join(x.get('operation','') for x in output.get('capabilities',[])[:10])+'.')
            elif step.preferred_tool in {'connector_read','connector_invoke'} and isinstance(output,dict):
                summaries.append(f"Connector {output.get('connector')} operation {output.get('operation')} is {output.get('status')} and its effect/response was independently verified.")
            elif step.preferred_tool in {'learning_plan_create','learning_plan_inspect'} and isinstance(output,dict):
                summaries.append(f"Learning plan for {output.get('subject','the requested subject')} is {output.get('status','UNKNOWN')} with {len(output.get('units',[]))} bounded units and {len(output.get('weaknesses',[]))} identified weak areas.")
            elif step.preferred_tool=='learning_assess' and isinstance(output,dict):
                plan=output.get('plan',{});summaries.append(f"Assessment recorded and independently reread; learning plan is {plan.get('status','UNKNOWN')} with {len(plan.get('weaknesses',[]))} weak areas requiring attention.")
            elif step.preferred_tool=='notification_explain' and isinstance(output,dict):
                summaries.append(f"Notification {output.get('notification_id')} surfaced because: {output.get('why','No explanation available')} Status: {output.get('status','unknown')}.")
            elif step.preferred_tool=='notification_inspect' and isinstance(output,dict):
                summaries.append(f"Notification: {output.get('title','Notification')} — {output.get('body','')} ({output.get('priority','NORMAL')}, {output.get('status','unknown')}).")
            elif step.preferred_tool=='notification_channels_inspect' and isinstance(output,dict):
                summaries.append('Notification channels: '+', '.join(f"{x.get('channel')} {x.get('availability')}" for x in output.get('channels',[])[:4])+'.')
            elif step.preferred_tool=='notification_delivery_inspect' and isinstance(output,dict):
                attempts=output.get('attempts') or ([output.get('attempt')] if output.get('attempt') else []);summaries.append('Notification delivery: '+', '.join(f"{x.get('channel')} {x.get('status')}" for x in attempts[:6])+'.')
            elif step.preferred_tool in {'notification_delivery_retry','notification_acknowledge'} and isinstance(output,dict):
                summaries.append(f"Notification delivery {output.get('channel')} is {output.get('status')}; persisted state was reread.")
            elif step.preferred_tool=='operations_snapshot' and isinstance(output,dict):
                waiting=len((output.get('operations') or {}).get('pending_approvals',[]));active=len((output.get('today') or {}).get('active_work',[]));attention=len((output.get('today') or {}).get('attention',[]));next_action=(output.get('next_action') or {}).get('title','No unresolved action');summaries.append(f"Personal operations: {active} active, {waiting} waiting for approval, {attention} needing attention. Next: {next_action}.")
            elif step.preferred_tool.startswith('daily_brief_') and isinstance(output,dict):
                open_items=[x for x in output.get('items',[]) if x.get('state')=='OPEN'];top='; '.join(f"{x.get('title')} ({x.get('source')})" for x in open_items[:3]);summaries.append(f"Daily brief {output.get('day')} is {output.get('status')} with {len(open_items)} open priorities"+(f": {top}." if top else '.'))
            elif step.preferred_tool=='perception_observe' and isinstance(output,dict):
                state=(output.get('fusion') or {}).get('state',{});pose=state.get('pose',{});fresh=output.get('freshness',{}).get('state','UNKNOWN');obs_id=(output.get('observation') or {}).get('observation_id')
                if pose:summaries.append(f"Current simulated perception for {output.get('observation',{}).get('robot_id','robot')} is x {float(pose.get('x',0)):.2f}, y {float(pose.get('y',0)):.2f}, theta {float(pose.get('theta',0)):.2f} ({fresh}; observation {obs_id}).")
            elif step.preferred_tool=='ros2_sim_status' and isinstance(output,dict):
                pose=output.get('pose',{});summaries.append(f"The simulation is at x {float(pose.get('x',0)):.2f}, y {float(pose.get('y',0)):.2f}.")
            elif step.preferred_tool=='ros2_sim_move' and isinstance(output,dict):
                pose=output.get('after',{});summaries.append(f"The simulation move completed and was independently verified at x {float(pose.get('x',0)):.2f}, y {float(pose.get('y',0)):.2f}.")
            elif step.preferred_tool=='specialist_delegate' and isinstance(output,dict):
                count=len(output.get('specialist_results',[]));findings=str(output.get('findings','')).strip();summaries.append(f"I coordinated {count} bounded specialist"+('' if count==1 else 's')+(' and verified the delegation.' if not findings else f". {findings[:700]}"))
            elif step.preferred_tool.startswith('automation_') and isinstance(output,dict):
                item=output.get('automation',{});summaries.append(f"Automation {item.get('id')} is {('enabled' if item.get('enabled') else 'paused')} and its state was independently reread.")
            elif step.preferred_tool=='image_generate' and isinstance(output,dict):
                summaries.append(f"Generated and independently verified {output.get('media_type','image')} artifact {output.get('artifact_id')} at {output.get('width')}×{output.get('height')} with SHA-256 {str(output.get('artifact_sha256',''))[:16]}….")
            elif step.preferred_tool=='engineering_inspect' and isinstance(output,dict):
                manifest=output.get('manifest',[])
                paths=[str(item.get('path')) for item in manifest if isinstance(item,dict) and isinstance(item.get('path'),str) and item.get('path')!='source_code.zip']
                important_order=[
                    'README.md',
                    'pyproject.toml',
                    'src/sparkle_gen2/core.py',
                    'src/sparkle_gen2/planner.py',
                    'src/sparkle_gen2/gen1.py',
                    'src/sparkle_gen2/cli.py',
                    'src/sparkle_gen2/models.py',
                    'src/sparkle_gen2/policy.py',
                    'src/sparkle_gen2/environment_gateway.py',
                    'src/sparkle_gen2/storage.py',
                    'src/sparkle_gen2/retrieval.py',
                    'src/sparkle_gen2/context_sources.py',
                ]
                important=[path for path in important_order if path in paths]
                if not important:
                    important=sorted(path for path in paths if path.startswith('src/sparkle_gen2/') and path.count('/')==2)[:12]
                count=output.get('file_count')
                digest=str(output.get('tree_sha256',''))
                detail=f"Verified the current repository snapshot ({count} files"
                if digest:
                    detail+=f", tree SHA-256 {digest[:16]}…"
                detail+=")."
                if important:
                    detail+=" Key Gen-2 files: "+", ".join(important)+"."
                summaries.append(detail)

            elif step.preferred_tool=='project_search' and isinstance(output,dict):
                value=output.get('value')
                if isinstance(value,list):
                    if not value:
                        summaries.append("No personal projects matched that search.")
                    else:
                        names=[]
                        for item in value[:8]:
                            if isinstance(item,dict):
                                name=item.get('name') or item.get('project_name') or item.get('title') or item.get('id')
                            else:
                                name=item
                            names.append(str(name))
                        summaries.append(f"Found {len(value)} personal project match"+('' if len(value)==1 else 'es')+": "+", ".join(names)+".")

            elif step.preferred_tool=='document_ingest' and isinstance(output,dict):
                summaries.append(f"Document {output.get('filename','document')} was locally extracted, structured, and independently reread with provenance.")
            elif step.preferred_tool=='document_search' and isinstance(output,dict):
                evidence=[]
                for item in output.get('items',[])[:3]:
                    meta=item.get('metadata',{});loc=meta.get('location',{});label=loc.get('label') or (f"{loc.get('kind')} {loc.get('index')}" if loc.get('index') is not None else loc.get('kind','source'));evidence.append(f"{str(item.get('text',''))[:280]} [{meta.get('filename','document')} — {label}]")
                if evidence:summaries.append('Grounded document evidence: '+' '.join(evidence))
        memory_candidates=self.memory.list(goal.goal_id)
        if goal.status==GoalStatus.COMPLETED:
            text='Completed and independently verified.'+(' '+ ' '.join(summaries) if summaries else '')
            proposed=[c for c in memory_candidates if c.state=='PROPOSED']
            if proposed:text+=f' I found {len(proposed)} useful memory candidate'+('' if len(proposed)==1 else 's')+'; nothing will be stored unless you approve it.'
        elif pending:text=f"I’m ready to {pending[-1].action.lower()}. This action requires your approval before I continue."
        elif goal.status==GoalStatus.BLOCKED:text='I’m blocked because policy, execution, or verification is unresolved. I did not mark the work complete.'
        else:text='Work is still in progress. Verified progress is saved and can be resumed from any authorized device.'
        gen1_approvals=[]
        if run.status in {'WAITING_FOR_GEN1_APPROVAL','WAITING_FOR_DELEGATION_APPROVAL'}:
            for step in plan.steps:
                output=(step.result or {}).get('output',{})
                if step.status==StepStatus.WAITING and isinstance(output,dict):
                    aid=output.get('proposal_id') or output.get('approval_id')
                    if isinstance(aid,str):gen1_approvals.append(aid)
                    for item in (output.get('provenance',{}) or {}).get('pending_approvals',[]):
                        pending_id=item.get('approval_id') if isinstance(item,dict) else None
                        if isinstance(pending_id,str) and pending_id not in gen1_approvals:gen1_approvals.append(pending_id)
        return {'goal_id':goal.goal_id,'task_run_id':run.task_run_id,'trace_id':run.trace_id,'status':goal.status.value,'text':text,'checked':checked,'verified':verified,'approvals':[a.approval_id for a in pending],'gen1_approvals':gen1_approvals,'memory_candidates':[c.to_dict() for c in memory_candidates],'delegations':self.store.delegations(goal_id=goal.goal_id),'model_provenance':self.store.provenance_for_goal(goal.goal_id),'criteria':[c.to_dict() for c in self.store.criteria_for_goal(goal.goal_id)]}
