from __future__ import annotations
import json,uuid
from time import monotonic
from datetime import UTC,datetime,timedelta
from typing import Any
from ...core_time import now
from ...gen1 import Gen1Gateway,ToolObservation
from ...domain.contracts.tool_protocol import ToolInput,ToolOutput,ToolError
from ...agents.base import AgentResult
from ...failures import FailureClassifier
from ...delegation import DelegationRequest,SpecialistDelegationService
from ...domain.models import *
from ...memory_orchestration import MemoryCandidateService
from ...learning_orchestration import LearningOrchestrator
from ...agent_registry import AgentRegistry
from ...automation_orchestration import AutomationOrchestrator
from ...observability import TraceRecorder
from ...planner import Gen1PlannerModel,PlannerError,PlannerModel
from ...policy import PolicyEngine
from ...permission_center import PermissionCenter
from ...storage import Gen2Store
from ...validation import PlanValidationError,PlanValidator
from ...application.execution.approval_service import ApprovalService

class ExecutionLifecycleService:
    """Own the PersonalAgent execution lifecycle; agent remains the compatibility facade."""

    @staticmethod
    def planning_error(exc):
        categories={'configuration_failure','authentication_failure','model_unavailable','timeout','rate_limited','provider_failure','connectivity_failure','malformed_response'}
        category=getattr(exc,'category',None)
        if not isinstance(category,str) or category not in categories:category='validation_failure' if isinstance(exc,PlanValidationError) else 'planning_failure'
        detail={'error_type':type(exc).__name__,'error_category':category,'retryable':getattr(exc,'retryable',False) is True}
        code=str(exc).split(':',1)[0]
        public_codes={'planner_invalid_json','planner_output_not_object','planner_success_criteria_invalid','planner_goal_criterion_not_object','planner_goal_criterion_missing_required_field','planner_goal_criterion_invalid_description','planner_goal_criterion_invalid_verification_method','planner_derived_field_forbidden','invalid_structured_output','model_capability_unavailable','gen2_capability_route_mismatch','planning_budget'}
        if code in public_codes:detail['error_code']=code
        component=getattr(exc,'schema_component',None)
        if isinstance(component,str) and component in {'step','model_provenance','proposal'}:
            fields=getattr(exc,'unexpected_fields',[])
            public_fields={'preferred_agent','preferred_model','model','agent','order','risk','status','description','tool','metadata'}
            detail['schema_component']=component;detail['error_category']='validation_failure'
            detail['unexpected_fields']=sorted({field for field in fields if isinstance(field,str) and field in public_fields}) if isinstance(fields,list) else []
        return detail

    @staticmethod
    def start(agent,request,*,user_id='user',target_device_id=None,target_device_kind=None,agent_profile=None):
            if not isinstance(request,str) or not request.strip():raise ValueError('request is required')
            if not isinstance(user_id,str) or not user_id.strip() or len(user_id)>256:raise ValueError('user_id is invalid')
            trace_id=uuid.uuid4().hex;target_device_id=str(target_device_id).strip() if target_device_id else None;target_device_kind=str(target_device_kind).strip().lower() if target_device_kind else None
            if target_device_id and len(target_device_id)>256:raise ValueError('target_device_id is invalid')
            if target_device_kind and target_device_kind not in {'computer','linux','mobile'}:raise ValueError('target_device_kind is invalid')
            goal=agent._goal(request,user_id,target_device_id,target_device_kind);goal.metadata['agent_profile']=dict(agent_profile or {});agent.store.save_goal(goal);agent.store.event(goal.goal_id,'goal_created',{'user_id':user_id,'target_device_kind':target_device_kind},now());agent.traces.record('goal','personal_agent','CREATED',goal_id=goal.goal_id,trace_id=trace_id,correlation={'user_id':user_id})
            goal.status=GoalStatus.UNDERSTANDING;goal.updated_at=now();agent.store.save_goal(goal)
            run=TaskRun(uuid.uuid4().hex,goal.goal_id,None,[],[],[],[],[],[],now(),now(),goal.deadline,'PLANNING',trace_id)
            agent.store.save_task_run(run);agent.graph.execution(goal,None,run)
            context=None
            if agent.context_provider is not None:
                try:
                    try:richer=agent.context_provider.gather(request,owner_user_id=goal.user_id,optimized=True)
                    except TypeError:richer=agent.context_provider.gather(request)
                    context={'source':'gen2-personal-context','rendered':str(richer.get('items',[]))[:6000],'item_count':richer.get('item_count',0)}
                except Exception as exc:
                    agent.store.event(goal.goal_id,'context_provider_failed',{'error_type':type(exc).__name__},now())
            if context is None:
                try:context=agent.gen1.retrieve_context(request,goal.context_requirements)
                except Exception as exc:
                    goal.status=GoalStatus.WAITING;run.status='CONTEXT_UNAVAILABLE';agent.store.save_goal(goal);agent.store.save_task_run(run);agent.graph.execution(goal,None,run)
                    agent.store.event(goal.goal_id,'context_unavailable',{'error_type':type(exc).__name__},now())
                    return {'goal_id':goal.goal_id,'task_run_id':run.task_run_id,'trace_id':trace_id,'status':'WAITING','text':'Context is unavailable. The saved execution can be retried.','checked':[],'verified':[],'approvals':[]}
            if agent.documents is not None:
                try:
                    docctx=agent.documents.context(request,user_id=user_id,k=5,max_chars=5000)
                    if docctx.get('item_count'):
                        context={'source':'documents+'+str(context.get('source','')),'rendered':('DOCUMENT_EVIDENCE:\n'+docctx['rendered']+'\nOTHER_CONTEXT:\n'+str(context.get('rendered','')))[:10000],'document_items':docctx['items']}
                        agent.store.event(goal.goal_id,'document_context_retrieved',{'item_count':docctx['item_count'],'document_ids':sorted({x['provenance']['document_id'] for x in docctx['items']})},now())
                except Exception as exc:agent.store.event(goal.goal_id,'document_context_failed',{'error_type':type(exc).__name__},now())
            remembered=agent.memory.recall(request,owner_user_id=user_id,limit=5)
            if remembered:context={'source':'completion_memory+'+str(context.get('source','')),'rendered':(str(remembered)+'\n'+str(context.get('rendered','')))[:6000]}
            health=agent._execution_health();capabilities=list(health.get('tools',[]))
            schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name') in capabilities}
            minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'capability_registry':agent.capabilities.definitions(),'tool_schemas':schemas,'deadline':goal.deadline,'constraints':goal.constraints}
            agent.store.event(goal.goal_id,'context_retrieved',{'source':minimal['source'],'capability_count':len(capabilities)},now());agent.traces.record('context','personal_context','RETRIEVED',goal_id=goal.goal_id,trace_id=trace_id,detail={'source':minimal['source'],'capability_count':len(capabilities)})
            last_error=None
            for attempt in range(agent.planner_retries+1):
                try:
                    proposal,provenance=agent._propose(goal,minimal,capabilities,run)
                    validator=PlanValidator(set(capabilities),agent.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
                    agent._validate_plan_arguments(plan,schemas,goal)
                    for planned_step in plan.steps:planned_step.preferred_agent=str((agent_profile or {}).get('agent_id','personal'))
                    agent.store.save_plan_proposal(proposal);agent.store.save_provenance(goal.goal_id,provenance)
                    for permission,risk in decisions:agent.store.save_permission(goal.goal_id,permission);agent.store.save_risk(goal.goal_id,risk)
                    break
                except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                    last_error=exc;detail={'attempt':attempt+1}|ExecutionLifecycleService.planning_error(exc);minimal['planning_feedback']=dict(detail);agent.store.event(goal.goal_id,'planning_failed',detail,now());agent.traces.record('planning','planner','FAILED',goal_id=goal.goal_id,trace_id=trace_id,detail=detail)
            else:
                goal.status=GoalStatus.BLOCKED if isinstance(last_error,PlanValidationError) else GoalStatus.WAITING;goal.updated_at=now();agent.store.save_goal(goal)
                run.status=goal.status.value;run.updated_at=now();agent.store.save_task_run(run);agent.graph.execution(goal,None,run)
                return {'goal_id':goal.goal_id,'task_run_id':run.task_run_id,'trace_id':trace_id,'status':goal.status.value,'text':'Planning could not produce a safe executable plan. The saved execution can be retried. No tools were executed.','planning_error':ExecutionLifecycleService.planning_error(last_error),'checked':[],'verified':[],'approvals':[]}
            goal.plan_id=plan.plan_id;goal.success_criteria=[c['description'] for c in proposal.success_criteria];goal.status=GoalStatus.PLANNED;goal.updated_at=now();agent.store.save_plan(plan);agent.store.save_goal(goal)
            criteria=list(proposal.success_criteria)
            criteria.extend([
                {'description':'Validated execution plan persisted','verification_method':'plan_persisted'},
                {'description':'All executable steps independently verified','verification_method':'all_steps_verified'},
            ])
            seen=set()
            for c in criteria:
                key=(c['description'],c['verification_method'])
                if key in seen:continue
                seen.add(key);agent.store.save_criterion(GoalSuccessCriterion(uuid.uuid4().hex,goal.goal_id,c['description'],c['verification_method'],CriterionStatus.PENDING,{}))
            agent.store.event(goal.goal_id,'plan_validated',{'plan_id':plan.plan_id,'proposal_id':proposal.proposal_id},now());agent.traces.record('planning','planner','VALIDATED',goal_id=goal.goal_id,trace_id=trace_id,detail={'plan_id':plan.plan_id})
            run.pending_steps=[s.step_id for s in plan.steps];run.status='RUNNING';run.updated_at=now();agent.store.save_task_run(run);agent.traces.record('task','personal_agent','STARTED',goal_id=goal.goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'plan_id':plan.plan_id})
            return agent.resume(goal.goal_id)

    @staticmethod
    def replan(agent,goal_id):
            goal=agent.store.load_goal(goal_id);old_plan=agent.store.load_plan(goal.plan_id) if goal.plan_id else None;old_run=agent.store.load_task_run_for_goal(goal_id);trace_id=old_run.trace_id or uuid.uuid4().hex
            if goal.status not in {GoalStatus.WAITING,GoalStatus.BLOCKED,GoalStatus.FAILED}:raise ValueError('goal is not eligible for replanning')
            if any(a.status==ApprovalStatus.PENDING for a in agent.store.approvals_for_goal(goal_id)):raise ValueError('pending approvals must be resolved before replanning')
            attempt=agent._replan_attempts(goal_id)+1;agent.store.event(goal_id,'replan_attempted',{'attempt':attempt},now());agent.traces.record('recovery','personal_agent','REPLAN_STARTED',goal_id=goal_id,task_run_id=old_run.task_run_id,trace_id=trace_id,detail={'attempt':attempt})
            context=agent.gen1.retrieve_context(goal.user_request,goal.context_requirements)
            if agent.context_provider is not None:
                try:
                    try:richer=agent.context_provider.gather(goal.user_request,owner_user_id=goal.user_id,optimized=True)
                    except TypeError:richer=agent.context_provider.gather(goal.user_request)
                    context={'source':'gen2-personal-context','rendered':str(richer.get('items',[]))[:6000],'item_count':richer.get('item_count',0)}
                except Exception as exc:agent.store.event(goal.goal_id,'context_provider_failed',{'error_type':type(exc).__name__},now())
            if agent.documents is not None:
                try:
                    docctx=agent.documents.context(goal.user_request,user_id=goal.user_id,k=5,max_chars=5000)
                    if docctx.get('item_count'):context={'source':'documents+'+str(context.get('source','')),'rendered':('DOCUMENT_EVIDENCE:\n'+docctx['rendered']+'\nOTHER_CONTEXT:\n'+str(context.get('rendered','')))[:10000],'document_items':docctx['items']}
                except Exception as exc:agent.store.event(goal.goal_id,'document_context_failed',{'error_type':type(exc).__name__},now())
            health=agent._execution_health();capabilities=list(health.get('tools',[]));schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name') in capabilities};minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'capability_registry':agent.capabilities.definitions(),'tool_schemas':schemas,'deadline':goal.deadline,'constraints':goal.constraints}
            failures=[e['payload'] for e in agent.store.events(goal_id) if e['event_type'] in {'planning_failed','planning_retry_failed'}]
            if failures:minimal['planning_feedback']={k:v for k,v in failures[-1].items() if k in {'error_type','error_category','error_code','schema_component','unexpected_fields'}}
            proposal,provenance=agent._propose(goal,minimal,capabilities,old_run);validator=PlanValidator(set(capabilities),agent.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
            agent._validate_plan_arguments(plan,schemas,goal)
            for planned_step in plan.steps:planned_step.preferred_agent=str((goal.metadata.get('agent_profile') or {}).get('agent_id','personal'))
            agent.store.save_plan_proposal(proposal);agent.store.save_provenance(goal_id,provenance)
            for permission,risk in decisions:agent.store.save_permission(goal_id,permission);agent.store.save_risk(goal_id,risk)
            old_run.status='SUPERSEDED';old_run.updated_at=now();agent.store.save_task_run(old_run);agent.store.clear_criteria(goal_id)
            goal.plan_id=plan.plan_id;goal.success_criteria=[c['description'] for c in proposal.success_criteria];goal.status=GoalStatus.PLANNED;agent.store.save_plan(plan)
            criteria=list(proposal.success_criteria)+[{'description':'Validated execution plan persisted','verification_method':'plan_persisted'},{'description':'All executable steps independently verified','verification_method':'all_steps_verified'}]
            seen=set()
            for c in criteria:
                key=(c['description'],c['verification_method'])
                if key in seen:continue
                seen.add(key);agent.store.save_criterion(GoalSuccessCriterion(uuid.uuid4().hex,goal_id,c['description'],c['verification_method'],CriterionStatus.PENDING,{}))
            run=TaskRun(uuid.uuid4().hex,goal_id,None,[],[],[x.step_id for x in plan.steps],[],[],[],now(),now(),goal.deadline,'RUNNING',trace_id);agent.store.save_task_run(run);agent.store.save_goal(goal);agent.store.event(goal_id,'replanned',{'old_plan_id':None if old_plan is None else old_plan.plan_id,'new_plan_id':plan.plan_id},now());agent.traces.record('planning','planner','REPLANNED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,detail={'plan_id':plan.plan_id})
            return agent.resume(goal_id)

    @staticmethod
    def continue_goal(agent,goal_id,instruction):
            if not isinstance(instruction,str) or not instruction.strip():raise ValueError('continuation instruction required')
            goal=agent.store.load_goal(goal_id)
            if any(a.status==ApprovalStatus.PENDING for a in agent.store.approvals_for_goal(goal_id)):raise ValueError('pending approvals must be resolved before continuation')
            original=goal.user_request;goal.user_request=(original+'\nContinuation: '+instruction.strip())[:12000];goal.status=GoalStatus.WAITING;agent.store.save_goal(goal);agent.store.event(goal_id,'goal_continuation_requested',{'previous_status':'COMPLETED' if agent.store.load_task_run_for_goal(goal_id).status=='COMPLETED' else 'NONTERMINAL'},now())
            try:return agent.replan(goal_id)
            except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                goal=agent.store.load_goal(goal_id);goal.status=GoalStatus.WAITING;agent.store.save_goal(goal);agent.store.event(goal_id,'continuation_planning_failed',ExecutionLifecycleService.planning_error(exc),now())
                run=agent.store.load_task_run_for_goal(goal_id);return {'goal_id':goal_id,'task_run_id':run.task_run_id,'trace_id':run.trace_id,'status':'WAITING','text':'Continuation is saved, but planning is unavailable. No tools were executed.','planning_error':ExecutionLifecycleService.planning_error(exc),'checked':[],'verified':[],'approvals':[],'gen1_approvals':[],'model_provenance':agent.store.provenance_for_goal(goal_id),'criteria':[c.to_dict() for c in agent.store.criteria_for_goal(goal_id)]}

    @staticmethod
    def cancel(agent,goal_id):
            goal=agent.store.load_goal(goal_id);plan=agent.store.load_plan(goal.plan_id);run=agent.store.load_task_run_for_goal(goal_id)
            if goal.status==GoalStatus.COMPLETED:raise ValueError('completed goal cannot be cancelled')
            agent.controls.request(goal_id,'CANCELLED')
            goal.status=GoalStatus.CANCELLED;run.status='CANCELLED';run.current_step=None;agent.store.cancel_pending_approvals(goal_id,now())
            for row in agent.store.delegations(goal_id=goal_id):agent.delegation.cancel(row['request']['request_id'])
            agent.store.event(goal_id,'goal_cancelled',{},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)

    @staticmethod
    def resume(agent,goal_id):
            goal=agent.store.load_goal(goal_id);run=agent.store.load_task_run_for_goal(goal_id)
            if not goal.plan_id:
                if run.status=='CAPTURED':raise ValueError('saved_task_needs_explicit_planning')
                if agent.controls.apply(goal,run) or goal.status==GoalStatus.CANCELLED:
                    agent.store.save_goal(goal);agent.store.save_task_run(run);agent.graph.execution(goal,None,run)
                    return {'goal_id':goal_id,'task_run_id':run.task_run_id,'status':goal.status.value,'run_status':run.status,'text':'Execution '+run.status.lower()+'.','checked':[],'verified':[],'approvals':[]}
                goal.status=GoalStatus.WAITING;agent.store.save_goal(goal)
                try:return agent.replan(goal_id)
                except (PlannerError,PlanValidationError,RuntimeError,ValueError,ConnectionError) as exc:
                    goal=agent.store.load_goal(goal_id);run=agent.store.load_task_run_for_goal(goal_id);goal.status=GoalStatus.BLOCKED if isinstance(exc,PlanValidationError) else GoalStatus.WAITING;run.status='PLANNING_UNAVAILABLE';run.updated_at=now();agent.store.save_goal(goal);agent.store.save_task_run(run);agent.graph.execution(goal,None,run)
                    agent.store.event(goal_id,'planning_retry_failed',ExecutionLifecycleService.planning_error(exc),now())
                    return {'goal_id':goal_id,'task_run_id':run.task_run_id,'status':goal.status.value,'run_status':run.status,'text':'Planning remains unavailable. The execution and its budget are saved.','checked':[],'verified':[],'approvals':[]}
            plan=agent.store.load_plan(goal.plan_id)
            if agent.controls.apply(goal,run):
                agent._persist(goal,plan,run);return agent.report(goal,plan,run)
            if not run.trace_id:run.trace_id=uuid.uuid4().hex;agent.store.save_task_run(run)
            trace_id=run.trace_id
            if goal.status==GoalStatus.COMPLETED:
                agent._analyze_completion_memory(goal,run);return agent.report(goal,plan,run)
            if goal.status==GoalStatus.CANCELLED:return agent.report(goal,plan,run)
            if run.status in {'ACTION_TIMEOUT','INTERRUPTED_ACTION'}:return agent.report(goal,plan,run)
            if agent._deadline_expired(goal.deadline):
                goal.status=GoalStatus.BLOCKED;run.status='DEADLINE_EXPIRED';agent.store.event(goal_id,'deadline_expired',{'deadline':goal.deadline},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
            health=agent._execution_health();schemas={d.get('name'):d for d in health.get('tool_definitions',[]) if d.get('name')}
            iterations=0
            for step in plan.steps:
                if step.status==StepStatus.VERIFIED:continue
                if agent.controls.apply(goal,run):
                    agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                history=agent.store.task_runs_for_goal(goal_id)
                calls=sum(int(x.get('iterations',0)) for x in history)
                elapsed=sum(float(x.get('active_runtime_seconds',0)) for x in history)
                if calls>=agent.max_iterations or elapsed>=agent.max_runtime_seconds:
                    goal.status=GoalStatus.BLOCKED;run.status='BUDGET_EXHAUSTED'
                    agent.store.event(goal_id,'execution_budget_exhausted',{'iterations':calls,'runtime_seconds':elapsed},now())
                    agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if step.status==StepStatus.EXECUTING and step.authorization_requirement!='ALLOW':
                    goal.status=GoalStatus.BLOCKED;run.status='INTERRUPTED_ACTION'
                    agent.store.event(goal_id,'interrupted_action_requires_review',{'step_id':step.step_id},now())
                    agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                argument_error=agent._schema_argument_error(step,schemas)
                if argument_error:
                    return agent._block_invalid_arguments(goal,plan,run,step,argument_error)
                if step.status==StepStatus.WAITING and run.status=='WAITING_FOR_DELEGATION_APPROVAL':
                    output=(step.result or {}).get('output',{});request_id=output.get('request_id') if isinstance(output,dict) else None
                    if not request_id:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    result=agent.delegation.reconcile(request_id)
                    if result is not None:step.result={'output':result.to_dict(),'verification':dict(result.verification)}
                    agent.store.event(goal_id,'delegation_approval_reconciled',{'request_id':request_id,'status':None if result is None else result.status,'verified':False if result is None else bool(result.verification.get('verified'))},now())
                    if result is not None and result.status=='COMPLETED' and result.verification.get('verified') is True:
                        step.status=StepStatus.VERIFIED
                        if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                        run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];run.status='RUNNING';agent.traces.record('verification','specialist_delegate','VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'method':'delegated_gen1_approval_reconciliation'});agent._persist(goal,plan,run);continue
                    if result is not None and result.status in {'FAILED','BLOCKED','CANCELLED'}:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    goal.status=GoalStatus.WAITING;agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if step.status==StepStatus.WAITING and run.status=='WAITING_FOR_GEN1_APPROVAL':
                    output=(step.result or {}).get('output',{});approval_id=output.get('proposal_id') if isinstance(output,dict) else None
                    status_fn=getattr(agent.gen1,'approval_status',None)
                    if approval_id and callable(status_fn):
                        state=status_fn(approval_id,step.preferred_tool);status=state.get('status')
                        agent.store.event(goal_id,'gen1_approval_reconciled',{'approval_id':approval_id,'status':status,'verified':bool(state.get('verified'))},now())
                        if status=='APPROVED' and state.get('verified'):
                            step.status=StepStatus.VERIFIED;step.result['verification']=state
                            if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                            run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];run.status='RUNNING';agent.traces.record('verification',step.preferred_tool,'VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id},detail={'method':'gen1_approval_reconciliation'});agent._persist(goal,plan,run);continue
                        if status in {'REJECTED','EXPIRED','CANCELLED'}:
                            step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                        goal.status=GoalStatus.WAITING;agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    goal.status=GoalStatus.WAITING;agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if any(next(x for x in plan.steps if x.step_id==d).status!=StepStatus.VERIFIED for d in step.dependencies):continue
                if iterations>=agent.max_iterations:goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
                iterations+=1
                if (step.preferred_tool.startswith('automation_') or step.preferred_tool in {'connector_invoke','image_generate','document_ingest','daily_brief_update','daily_brief_close','learning_plan_create','learning_assess','workspace_test'}) and any(k in step.arguments for k in {'approved','approval_id','grant_id','authorization_override'}):
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'model_authority_rejected',{'step_id':step.step_id},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if step.preferred_tool=='workspace_test' and (set(step.arguments)!={'project_name'} or not isinstance(step.arguments.get('project_name'),str) or not step.arguments['project_name'].strip()):
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'workspace_test_scope_rejected',{'step_id':step.step_id},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                permission,risk=agent.policy.evaluate(step.preferred_tool,'user',step.description,now())
                if permission.effect==PermissionEffect.DENY:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
                if permission.effect==PermissionEffect.REQUIRE_APPROVAL:
                    if agent._contains_model_authority(step.arguments):
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'model_authority_rejected',{'step_id':step.step_id},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    approval=agent._approval_for(goal_id,step.step_id)
                    exact_scope=agent._exact_approval_scope(goal,step)
                    if approval is None:
                        approval=Approval(uuid.uuid4().hex,goal_id,run.task_run_id,step.step_id,step.description,step.preferred_tool,risk.level,now(),None,ApprovalStatus.PENDING,exact_scope)
                        agent.store.save_approval(approval);run.approvals.append(approval.approval_id);agent.store.event(goal_id,'approval_required',{'approval_id':approval.approval_id,'step_id':step.step_id},now())
                    if approval.status==ApprovalStatus.PENDING and approval.expires_at and agent._deadline_expired(approval.expires_at):
                        approval.status=ApprovalStatus.EXPIRED;approval.decision_at=now();agent.store.save_approval(approval);agent.store.event(goal_id,'approval_expired',{'approval_id':approval.approval_id},now())
                    if approval.status==ApprovalStatus.PENDING:
                        step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_APPROVAL';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    if approval.status==ApprovalStatus.EXPIRED:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='APPROVAL_EXPIRED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    if approval.status==ApprovalStatus.REJECTED:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    if approval.status==ApprovalStatus.APPROVED and approval.requested_scope!=exact_scope:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED'
                        event_type='automation_approval_scope_mismatch' if step.preferred_tool.startswith('automation_') else 'approval_scope_mismatch'
                        agent.store.event(goal_id,event_type,{'approval_id':approval.approval_id,'step_id':step.step_id,'tool':step.preferred_tool},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                delegation_request=None;request_id=None;specialists=[]
                if step.preferred_tool=='specialist_delegate':
                    args=dict(step.arguments);specialists=list(args.get('specialists',[]));objective=str(args.get('objective') or step.description);authorized_action=args.get('authorized_action');request_id=agent.delegation.deterministic_id(goal_id,run.task_run_id,step.step_id,specialists,objective,authorized_action);inputs=dict(args.get('inputs',{}))
                    if step.dependencies:
                        dependency_results={}
                        for dep_id in step.dependencies:
                            dep=next(x for x in plan.steps if x.step_id==dep_id);value=(dep.result or {}).get('output')
                            if isinstance(value,dict):dependency_results[dep_id]={'findings':str(value.get('findings',''))[:2000],'evidence':list(value.get('evidence',[]))[:20],'verification':dict((dep.result or {}).get('verification',{}))}
                        if dependency_results:inputs['verified_dependency_results']=dependency_results
                    trusted_scope={}
                    if isinstance(authorized_action,dict) and authorized_action.get('tool')=='workspace_package':
                        fn=getattr(agent.gen1,'package_source_identity',None)
                        if not callable(fn):
                            step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'delegation_package_source_unavailable',{},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                        try:trusted_scope={'package_source':fn(str((authorized_action.get('arguments') or {}).get('project_name','')))}
                        except Exception as exc:
                            step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'delegation_package_source_invalid',{'error_type':type(exc).__name__},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    delegation_request=DelegationRequest(request_id,goal_id,run.task_run_id,trace_id,goal.user_id,str(args.get('capability','reasoning')),specialists,objective,inputs,list(args.get('constraints',goal.constraints)),goal.deadline,step.risk,list(args.get('required_evidence',step.success_criteria)),now(),authorized_action,None,trusted_scope)
                    try:
                        record=agent.delegation.prepare(delegation_request);delegation_request=record.request;agent.store.event(goal_id,'delegation_prepared',{'request_id':request_id,'specialists':specialists},now());agent.traces.record('delegation','gen1_run_multi','PREPARED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists,'user_id':goal.user_id});agent._persist(goal,plan,run)
                        if delegation_request.authorized_action is not None and not delegation_request.grant_id:
                            approval=agent._approval_for(goal_id,step.step_id);scope=agent.delegation.grants.approval_scope(delegation_request);tool=str(delegation_request.authorized_action.get('tool'));_,write_risk=agent.policy.evaluate(tool,'user',scope,now())
                            if approval is None:
                                approval=Approval(uuid.uuid4().hex,goal_id,run.task_run_id,step.step_id,f'Authorize {specialists[0]} specialist to use {tool}', 'specialist_delegate',write_risk.level,now(),(datetime.now(UTC)+timedelta(minutes=15)).isoformat(),ApprovalStatus.PENDING,scope)
                                agent.store.save_approval(approval);run.approvals.append(approval.approval_id);agent.store.event(goal_id,'delegation_grant_approval_required',{'approval_id':approval.approval_id,'request_id':request_id,'specialist':specialists[0],'tool':tool},now());agent.traces.record('authorization','delegation_grant','APPROVAL_REQUIRED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'request_id':request_id},detail={'specialist':specialists[0],'tool':tool})
                            if approval.status==ApprovalStatus.PENDING and approval.expires_at and agent._deadline_expired(approval.expires_at):
                                approval.status=ApprovalStatus.EXPIRED;approval.decision_at=now();agent.store.save_approval(approval)
                            if approval.status==ApprovalStatus.PENDING:
                                step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_APPROVAL';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                            if approval.status in {ApprovalStatus.REJECTED,ApprovalStatus.EXPIRED,ApprovalStatus.CANCELLED}:
                                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                            grant=agent.delegation.grants.issue(delegation_request,approval);record=agent.delegation.attach_grant(request_id,grant.grant_id);delegation_request=record.request;agent.store.event(goal_id,'delegation_grant_issued',{'grant_id':grant.grant_id,'approval_id':approval.approval_id,'request_id':request_id,'specialist':specialists[0],'tool':grant.capability,'expires_at':grant.expires_at},now());agent.traces.record('authorization','delegation_grant','ISSUED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'grant_id':grant.grant_id,'request_id':request_id},detail={'specialist':specialists[0],'tool':grant.capability,'issuer':grant.issuer,'expires_at':grant.expires_at})
                    except Exception as exc:
                        output={'status':'FAILED','request_id':request_id,'failure':{'category':type(exc).__name__,'reason':str(exc)[:300]}};obs=ToolObservation(False,step.preferred_tool,output,{'verified':False,'method':'delegation validation/authorization failed'})
                        step.result={'output':obs.output,'verification':obs.verification};agent.store.event(goal_id,'delegation_observed',{'request_id':request_id,'status':'FAILED','specialists':specialists},now());agent.traces.record('delegation','gen1_run_multi','FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists});step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if step.attempts>step.retry_limit:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
                goal.status=GoalStatus.EXECUTING;step.status=StepStatus.EXECUTING;step.attempts+=1;run.iterations+=1;run.resource_usage['tool_calls']=run.iterations;run.current_step=step.step_id;agent._persist(goal,plan,run);agent.traces.record('action',step.preferred_tool,'STARTED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
                action_started=monotonic()
                try:
                    if step.preferred_tool=='specialist_delegate':
                        result=agent.delegation.execute(delegation_request);output=result.to_dict();obs=ToolObservation(result.status=='COMPLETED',step.preferred_tool,output,dict(result.verification))
                        if delegation_request.grant_id:
                            try:
                                consumed=agent.delegation.grants.load(delegation_request.grant_id)
                                if consumed.state=='CONSUMED':
                                    agent.store.event(goal_id,'delegation_grant_consumed',{'grant_id':consumed.grant_id,'approval_id':consumed.approval_id,'request_id':request_id,'specialist':consumed.allowed_specialists[0],'tool':consumed.capability,'consumed_at':consumed.consumed_at},now());agent.traces.record('authorization','delegation_grant','CONSUMED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':consumed.approval_id,'grant_id':consumed.grant_id,'request_id':request_id},detail={'specialist':consumed.allowed_specialists[0],'tool':consumed.capability,'issuer':consumed.issuer})
                            except Exception:pass
                        agent.store.event(goal_id,'delegation_observed',{'request_id':request_id,'status':output.get('status'),'specialists':specialists},now());agent.traces.record('delegation','gen1_run_multi',str(output.get('status','FAILED')),goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':request_id},detail={'specialists':specialists,'grant_id':delegation_request.grant_id})
                        if result.status=='WAITING_APPROVAL':
                            step.result={'output':obs.output,'verification':obs.verification};step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_DELEGATION_APPROVAL'
                            for pending_item in result.provenance.get('pending_approvals',[]):
                                aid=pending_item.get('approval_id')
                                if isinstance(aid,str) and aid not in run.approvals:run.approvals.append(aid)
                            agent.store.event(goal_id,'delegated_gen1_approval_required',{'request_id':request_id,'approvals':result.provenance.get('pending_approvals',[])},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                    else:
                        request=ToolInput(step.preferred_tool,dict(step.arguments),goal.user_id,goal_id,run.task_run_id,step.step_id)
                        obs=agent.tool_dispatch.invoke(agent,goal,plan,run,step,request=request)
                except Exception as exc:
                    transient=isinstance(exc,(TimeoutError,ConnectionError))
                    obs=ToolObservation(False,step.preferred_tool,{'error':'temporarily_unavailable' if transient else 'execution_failed','error_type':type(exc).__name__},{'verified':False,'method':'execution exception'})
                finally:
                    action_elapsed=max(0.0,monotonic()-action_started)
                    run.active_runtime_seconds+=action_elapsed
                    agent.controls.apply(goal,run)
                    agent.store.save_task_run(run)
                if action_elapsed>step.timeout_seconds:
                    step.result={'output':obs.output,'verification':obs.verification,'timeout':True}
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='ACTION_TIMEOUT'
                    agent.store.event(goal_id,'action_timeout',{'step_id':step.step_id,'duration':action_elapsed,'limit':step.timeout_seconds},now())
                    agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if not isinstance(obs.output,dict) or not isinstance(obs.verification,dict):
                    obs=ToolObservation(False,step.preferred_tool,{'error':'invalid_tool_output'},{'verified':False,'reason':'tool_protocol_violation'})
                obs.verification=agent.verifier.verify(step,obs)
                error=None if obs.ok else ToolError(str(obs.output.get('error','execution_failed')),'The adapter did not complete the requested action.')
                step.result={'output':obs.output,'verification':obs.verification,'tool_output':ToolOutput(step.preferred_tool,obs.ok and obs.verification.get('verified') is True and not obs.requires_approval,obs.output,obs.verification,error=error,metadata={'goal_id':goal_id,'task_run_id':run.task_run_id,'step_id':step.step_id}).to_dict()};agent.store.event(goal_id,'tool_observed',{'tool':step.preferred_tool,'ok':obs.ok},now());agent.traces.record('observation',step.preferred_tool,'OK' if obs.ok else 'FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
                if not obs.ok:
                    if isinstance(obs.output,dict) and obs.output.get('error') in {'missing_required_argument','invalid_arguments','unexpected_arguments'}:
                        return agent._block_invalid_arguments(goal,plan,run,step,dict(obs.output))
                    step.status=StepStatus.FAILED
                    if step.step_id not in run.failed_steps:run.failed_steps.append(step.step_id)
                    decision=agent.failures.classify(obs.output,attempts=step.attempts,retry_limit=step.retry_limit);run.recovery_history.append(decision.to_dict()|{'step_id':step.step_id,'attempt':step.attempts,'created_at':now()});agent.store.event(goal_id,'failure_classified',decision.to_dict()|{'step_id':step.step_id},now());agent.traces.record('recovery','failure_classifier',decision.action,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id},detail={'category':decision.category,'retryable':decision.retryable})
                    if decision.action=='REPLAN':
                        goal.status=GoalStatus.BLOCKED;run.status='REPLAN';agent._persist(goal,plan,run)
                        if agent._replan_attempts(goal_id)<agent.max_replans:
                            try:return agent.replan(goal_id)
                            except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                                goal=agent.store.load_goal(goal_id);run=agent.store.load_task_run_for_goal(goal_id);goal.status=GoalStatus.BLOCKED;run.status='REPLAN_FAILED';agent.store.event(goal_id,'automatic_replan_failed',{'error_type':type(exc).__name__},now());agent.traces.record('recovery','personal_agent','REPLAN_FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=run.trace_id or trace_id,detail={'error_type':type(exc).__name__});agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                        return agent.report(goal,plan,run)
                    goal.status=GoalStatus.WAITING if decision.action in {'RETRY','WAIT_USER','WAIT_EXTERNAL'} else GoalStatus.BLOCKED;run.status=decision.action;agent._persist(goal,plan,run)
                    if decision.action=='RETRY' and agent.auto_retry and permission.effect==PermissionEffect.ALLOW and not agent.controls.apply(goal,run):
                        return agent.resume(goal_id)
                    return agent.report(goal,plan,run)
                goal.status=GoalStatus.VERIFYING
                if not obs.verification.get('verified'):
                    step.status=StepStatus.FAILED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';agent.store.event(goal_id,'verification_failed',obs.verification,now());agent.traces.record('verification',step.preferred_tool,'FAILED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id});agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                if obs.requires_approval:
                    step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_GEN1_APPROVAL'
                    if obs.approval_id and obs.approval_id not in run.approvals:run.approvals.append(obs.approval_id)
                    agent.store.event(goal_id,'gen1_approval_required',{'approval_id':obs.approval_id,'tool':step.preferred_tool},now());agent._persist(goal,plan,run);return agent.report(goal,plan,run)
                step.status=StepStatus.VERIFIED
                run.failed_steps=[x for x in run.failed_steps if x!=step.step_id]
                if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];agent.store.event(goal_id,'step_verified',{'step_id':step.step_id},now());agent.traces.record('verification',step.preferred_tool,'VERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id})
            if agent.controls.apply(goal,run):
                agent._persist(goal,plan,run);return agent.report(goal,plan,run)
            agent._evaluate_goal(goal,plan)
            if all(c.status==CriterionStatus.SATISFIED for c in agent.store.criteria_for_goal(goal_id)) and all(s.status==StepStatus.VERIFIED for s in plan.steps):
                goal.status=GoalStatus.COMPLETED;run.status='COMPLETED';run.current_step=None;agent.store.event(goal_id,'goal_completed',{'authority':'deterministic_goal_evaluator'},now());agent.traces.record('goal','deterministic_goal_evaluator','COMPLETED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id)
            elif goal.status not in {GoalStatus.BLOCKED,GoalStatus.WAITING}:goal.status=GoalStatus.WAITING;run.status='WAITING'
            agent._persist(goal,plan,run)
            if goal.status==GoalStatus.COMPLETED:agent._analyze_completion_memory(goal,run)
            return agent.report(goal,plan,run)

    @staticmethod
    def _evaluate_goal(agent,goal,plan):
            steps={s.step_id:s for s in plan.steps}
            for c in agent.store.criteria_for_goal(goal.goal_id):
                if c.verification_method=='all_steps_verified':ok=all(s.status==StepStatus.VERIFIED for s in plan.steps);evidence={'verified_steps':[s.step_id for s in plan.steps if s.status==StepStatus.VERIFIED]}
                elif c.verification_method=='plan_persisted':
                    try:agent.store.load_plan(plan.plan_id);ok=True;evidence={'plan_id':plan.plan_id,'persisted':True}
                    except KeyError:ok=False;evidence={'plan_id':plan.plan_id,'persisted':False}
                else:
                    sid=c.verification_method.split(':',1)[1];ok=steps[sid].status==StepStatus.VERIFIED;evidence={'step_id':sid,'status':steps[sid].status.value}
                c.status=CriterionStatus.SATISFIED if ok else CriterionStatus.PENDING;c.evidence=evidence;agent.store.save_criterion(c)

    @staticmethod
    def _persist(agent,goal,plan,run):
            agent.controls.apply(goal,run)
            goal.updated_at=now();run.updated_at=now();agent.store.save_plan(plan);agent.store.save_goal(goal);agent.store.save_task_run(run)
            agent.graph.execution(goal,plan,run)

    @staticmethod
    def report(agent,goal,plan,run):
            checked=[s.preferred_tool for s in plan.steps if s.result];verified=[s.description for s in plan.steps if s.status==StepStatus.VERIFIED]
            pending=[a for a in agent.store.approvals_for_goal(goal.goal_id) if a.status==ApprovalStatus.PENDING]
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
            memory_candidates=agent.memory.list(goal.goal_id)
            if goal.status==GoalStatus.COMPLETED:
                text='Completed and independently verified.'+(' '+ ' '.join(summaries) if summaries else '')
                proposed=[c for c in memory_candidates if c.state=='PROPOSED']
                if proposed:text+=f' I found {len(proposed)} useful memory candidate'+('' if len(proposed)==1 else 's')+'; nothing will be stored unless you approve it.'
            elif run.status=='PAUSED':text='Execution is paused. Verified progress is saved. Resume when ready.'
            elif goal.status==GoalStatus.CANCELLED:text='Execution is cancelled. Saved observations and verified results remain available.'
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
            result={'goal_id':goal.goal_id,'task_run_id':run.task_run_id,'trace_id':run.trace_id,'status':goal.status.value,'run_status':run.status,'artifacts':list(run.artifacts),'resource_usage':{'iterations':run.iterations,'active_runtime_seconds':run.active_runtime_seconds,**run.resource_usage},'text':text,'checked':checked,'verified':verified,'approvals':[a.approval_id for a in pending],'gen1_approvals':gen1_approvals,'memory_candidates':[c.to_dict() for c in memory_candidates],'delegations':agent.store.delegations(goal_id=goal.goal_id),'model_provenance':agent.store.provenance_for_goal(goal.goal_id),'criteria':[c.to_dict() for c in agent.store.criteria_for_goal(goal.goal_id)]}
            result['agent_result']=AgentResult.from_report(result).to_dict()
            return result
