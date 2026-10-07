from __future__ import annotations
import json,uuid
from time import monotonic
from datetime import UTC,datetime,timedelta
from typing import Any
from ..core_time import now
from ..gen1 import Gen1Gateway,ToolObservation
from ..failures import FailureClassifier
from ..delegation import DelegationRequest,SpecialistDelegationService
from ..domain.models import *
from ..memory_orchestration import MemoryCandidateService
from ..learning_orchestration import LearningOrchestrator
from ..agent_registry import AgentRegistry
from ..automation_orchestration import AutomationOrchestrator
from ..observability import TraceRecorder
from ..planner import Gen1PlannerModel,PlannerError,PlannerModel
from ..policy import PolicyEngine
from ..permission_center import PermissionCenter
from ..storage import Gen2Store
from ..validation import PlanValidationError,PlanValidator
from ..application.execution.approval_service import ApprovalService
from ..application.execution.run_controls import RunControlService
from ..domain.contracts.tool_protocol import input_errors
from ..application.personal_os.graph import PersonalGraphService
from ..application.system.tool_system import CapabilityCatalog
from ..application.execution.tool_dispatch import ExecutionToolDispatcher
from ..application.execution.verification import StepVerifier
from ..application.execution.budgets import ResourceBudget

class PersonalAgent:
    def __init__(self,store:Gen2Store,gen1:Gen1Gateway,*,planner:PlannerModel|None=None,policy:PolicyEngine|None=None,context_provider=None,connector_manager=None,document_service=None,image_service=None,perception_service=None,operations_service=None,daily_os_service=None,notification_service=None,learning_service=None,tracer=None,max_iterations:int=12,planner_retries:int=1,max_replans:int=1,auto_retry:bool=False,max_runtime_seconds:float=300.0):
        if not 1<=max_iterations<=100:raise ValueError('max_iterations out of range')
        if not 0<=planner_retries<=2:raise ValueError('planner_retries out of range')
        if not 0<=max_replans<=3:raise ValueError('max_replans out of range')
        self.store=store;self.gen1=gen1;self.agent_registry=AgentRegistry();self.planner=planner or Gen1PlannerModel(gen1);self.policy=policy or PolicyEngine();self.context_provider=context_provider;self.connectors=connector_manager;self.documents=document_service;self.images=image_service;self.perception=perception_service;self.daily_os=daily_os_service;self.operations=operations_service;self.notifications=notification_service;self.notification_delivery=getattr(notification_service,'delivery',None);self.learning=learning_service;self.traces=tracer or TraceRecorder(store);self.memory=MemoryCandidateService(store,gen1,self.policy);self.delegation=SpecialistDelegationService(store,gen1,self.policy);self.failures=FailureClassifier();self.max_iterations=max_iterations;self.planner_retries=planner_retries;self.max_replans=max_replans
        self._execution_health_cache=None
        self._execution_health_cache_at=0.0
        self._execution_health_ttl=5.0
        self.approvals=ApprovalService(store,traces=self.traces)
        self.controls=RunControlService(store)
        self.graph=PersonalGraphService(store)
        self.capabilities=CapabilityCatalog();self.tool_dispatch=ExecutionToolDispatcher();self.verifier=StepVerifier()
        if not 0<float(max_runtime_seconds)<=86400:raise ValueError('max_runtime_seconds out of range')
        self.auto_retry=bool(auto_retry)
        self.max_runtime_seconds=float(max_runtime_seconds)
        from ..application.execution.lifecycle_service import ExecutionLifecycleService
        self.execution=ExecutionLifecycleService()
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
        base['native_tools']=list(base.get('tools',[]))
        tools=list(base.get('tools',[]));definitions=list(base.get('tool_definitions',[]))
        if self.delegation.available() and 'specialist_delegate' not in tools:
            tools.append('specialist_delegate');definitions.append({'name':'specialist_delegate','description':'Delegate bounded analysis to certified Gen-1 specialists. Read-only is the default: state-changing tools are hidden and denied. An exact authorized_action requires a separate human approval. Specialists are explicit, unique, and allowlisted.','parameters':{'type':'object','properties':{'specialists':{'type':'array','items':{'type':'string'},'minItems':1},'objective':{'type':'string'},'inputs':{'type':'object'},'constraints':{'type':'array','items':{'type':'string'}},'required_evidence':{'type':'array','items':{'type':'string'}},'read_only':{'type':'boolean'},'authorized_action':{'type':'object','properties':{'tool':{'type':'string'},'arguments':{'type':'object'}},'required':['tool','arguments'],'additionalProperties':False}},'required':['specialists','objective'],'additionalProperties':False}})
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
        base['tools']=sorted(set(tools));base['tool_definitions']=definitions
        self.capabilities=CapabilityCatalog.from_health(base,self.policy,timestamp=now(),agent_ids=tuple(x['agent_id'] for x in self.agent_registry.list()))
        base['capability_registry']=self.capabilities.definitions()
        return base
    def invalidate_execution_health_cache(self):
        self._execution_health_cache=None
        self._execution_health_cache_at=0.0

    def _propose(self,goal,context,capabilities,run):
        usage=ResourceBudget.usage(self.store.task_runs_for_goal(goal.goal_id))
        limits={'planning_calls':8,'runtime_seconds':self.max_runtime_seconds}
        configured=(goal.metadata or {}).get('resource_limits') or {}
        for key in ('planning_calls','reported_tokens'):
            if key in configured:limits[key]=min(float(configured[key]),limits.get(key,float('inf')))
        if 'reported_tokens' in limits:usage['reported_tokens']=None
        decision=ResourceBudget(limits).check(usage,reservations={'planning_calls':1})
        if not decision['allowed']:raise PlanValidationError('planning_budget:'+decision['reason']+':'+decision['resource'])
        run.resource_usage['planning_calls']=int(run.resource_usage.get('planning_calls',0))+1
        previous_status=run.status;run.status='PLANNING'
        self.store.save_task_run(run);started=monotonic()
        try:
            proposal,provenance=self.planner.propose(goal,context,capabilities)
            tokens=provenance.resource_usage
            total=tokens.get('total_tokens')
            if total is None and tokens:total=sum(tokens.get(k,0) for k in ('input_tokens','output_tokens','prompt_tokens','completion_tokens'))
            if total is not None:run.resource_usage['reported_tokens']=int(run.resource_usage.get('reported_tokens',0))+int(total)
            return proposal,provenance
        finally:
            run.status=previous_status;run.active_runtime_seconds+=max(0.0,monotonic()-started);run.updated_at=now();self.store.save_task_run(run)

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
        invalid=input_errors(args,parameters)
        if invalid:
            return {'error':'invalid_arguments','reason':'tool schema validation failed','fields':invalid}
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
    def start(self, request, *, user_id='user', target_device_id=None, target_device_kind=None,agent_id='personal'):
        profile=self.agent_registry.resolve(agent_id)
        return self.execution.start(self, request, user_id=user_id, target_device_id=target_device_id, target_device_kind=target_device_kind,agent_profile=profile.to_dict())
    def respond(self, request):
        from .base import AgentResponse,AgentResult
        agent_id=request.metadata.get('agent_id','personal')
        report=self.start(request.text,user_id=request.user_id,agent_id=agent_id)
        return AgentResponse(report['text'],report['status'],agent_id,AgentResult.from_report(report).to_dict())
    def _replan_attempts(self,goal_id):return sum(1 for e in self.store.events(goal_id) if e['event_type']=='replan_attempted')
    def replan(self, goal_id):
        return self.execution.replan(self, goal_id)
    def continue_goal(self, goal_id, instruction):
        return self.execution.continue_goal(self, goal_id, instruction)

    def _approval_for(self,goal_id,step_id):
        return self.approvals.find_for_step(goal_id,step_id)
    @staticmethod
    def _contains_model_authority(value):
        return ApprovalService.contains_model_authority(value)
    @staticmethod
    def _exact_approval_scope(goal,step):
        return ApprovalService.exact_scope(goal,step)
    def _workspace_test_execution_grant(self,goal,run,step,approval,scope):
        return self.approvals.workspace_test_grant(goal,run,step,approval,scope)
    def decide_approval(self,approval_id:str,decision:str,*,actor:str='user'):
        return self.approvals.decide(approval_id,decision,actor=actor)
    def _deadline_expired(self,deadline):
        return ApprovalService.deadline_expired(deadline)
    def cancel(self, goal_id):
        return self.execution.cancel(self, goal_id)
    def pause(self, goal_id):
        goal=self.store.load_goal(goal_id)
        if goal.status in {GoalStatus.COMPLETED,GoalStatus.CANCELLED}:raise ValueError('terminal goal cannot be paused')
        plan=self.store.load_plan(goal.plan_id);run=self.store.load_task_run_for_goal(goal_id)
        self.controls.request(goal_id,'PAUSED')
        self._persist(goal,plan,run)
        self.store.event(goal_id,'execution_paused',{},now())
        return self.report(goal,plan,run)
    def unpause(self, goal_id):
        goal=self.store.load_goal(goal_id)
        if goal.status==GoalStatus.CANCELLED:raise ValueError('cancelled goal cannot resume')
        self.controls.request(goal_id,'RUNNING')
        self.store.event(goal_id,'execution_resumed',{},now())
        return self.resume(goal_id)
    def resume(self, goal_id):
        return self.controls.execute(self,goal_id,lambda:self.execution.resume(self,goal_id))
    def _analyze_completion_memory(self,goal,run):
        before={c.candidate_id for c in self.memory.list(goal.goal_id)};items=self.memory.analyze_completion(goal,run,self.store.criteria_for_goal(goal.goal_id))
        for candidate in items:
            self.graph.memory(candidate)
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
    def _evaluate_goal(self, goal, plan):
        return self.execution._evaluate_goal(self, goal, plan)
    def _persist(self, goal, plan, run):
        return self.execution._persist(self, goal, plan, run)
    def report(self, goal, plan, run):
        return self.execution.report(self, goal, plan, run)
