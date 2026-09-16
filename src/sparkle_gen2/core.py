from __future__ import annotations
import uuid
from datetime import UTC,datetime
from typing import Any
from .core_time import now
from .gen1 import Gen1Gateway
from .models import *
from .planner import Gen1PlannerModel,PlannerError,PlannerModel
from .policy import PolicyEngine
from .storage import Gen2Store
from .validation import PlanValidationError,PlanValidator

class PersonalAgent:
    def __init__(self,store:Gen2Store,gen1:Gen1Gateway,*,planner:PlannerModel|None=None,policy:PolicyEngine|None=None,max_iterations:int=12,planner_retries:int=1):
        if not 1<=max_iterations<=100:raise ValueError('max_iterations out of range')
        if not 0<=planner_retries<=2:raise ValueError('planner_retries out of range')
        self.store=store;self.gen1=gen1;self.planner=planner or Gen1PlannerModel(gen1);self.policy=policy or PolicyEngine();self.max_iterations=max_iterations;self.planner_retries=planner_retries
    def _goal(self,request):
        stamp=now();return Goal(uuid.uuid4().hex,request.strip(),' '.join(request.strip().split()),success_criteria=[],context_requirements=['relevant Gen-1 context'],created_at=stamp,updated_at=stamp,status=GoalStatus.CREATED)
    def start(self,request):
        if not isinstance(request,str) or not request.strip():raise ValueError('request is required')
        goal=self._goal(request);self.store.save_goal(goal);self.store.event(goal.goal_id,'goal_created',{},now())
        goal.status=GoalStatus.UNDERSTANDING;goal.updated_at=now();self.store.save_goal(goal)
        context=self.gen1.retrieve_context(request,goal.context_requirements);health=self.gen1.health();capabilities=list(health.get('tools',[]))
        minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'deadline':goal.deadline,'constraints':goal.constraints}
        self.store.event(goal.goal_id,'context_retrieved',{'source':minimal['source'],'capability_count':len(capabilities)},now())
        last_error=None
        for attempt in range(self.planner_retries+1):
            try:
                proposal,provenance=self.planner.propose(goal,minimal,capabilities);self.store.save_plan_proposal(proposal);self.store.save_provenance(goal.goal_id,provenance)
                validator=PlanValidator(set(capabilities),self.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
                for permission,risk in decisions:self.store.save_permission(goal.goal_id,permission);self.store.save_risk(goal.goal_id,risk)
                break
            except (PlannerError,PlanValidationError,RuntimeError,ValueError) as exc:
                last_error=exc;self.store.event(goal.goal_id,'planning_failed',{'attempt':attempt+1,'error_type':type(exc).__name__,'reason':str(exc)[:200]},now())
        else:
            goal.status=GoalStatus.BLOCKED if isinstance(last_error,PlanValidationError) else GoalStatus.WAITING;goal.updated_at=now();self.store.save_goal(goal)
            return {'goal_id':goal.goal_id,'status':goal.status.value,'text':f'Planning could not produce a safe executable plan: {last_error}. No tools were executed.','checked':[],'verified':[],'approvals':[]}
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
        self.store.event(goal.goal_id,'plan_validated',{'plan_id':plan.plan_id,'proposal_id':proposal.proposal_id},now())
        run=TaskRun(uuid.uuid4().hex,goal.goal_id,None,[],[],[s.step_id for s in plan.steps],[],[],[],now(),now(),goal.deadline,'RUNNING',uuid.uuid4().hex);self.store.save_task_run(run)
        return self.resume(goal.goal_id)
    def replan(self,goal_id):
        goal=self.store.load_goal(goal_id);old_plan=self.store.load_plan(goal.plan_id);old_run=self.store.load_task_run_for_goal(goal_id)
        if goal.status not in {GoalStatus.WAITING,GoalStatus.BLOCKED,GoalStatus.FAILED}:raise ValueError('goal is not eligible for replanning')
        if any(a.status==ApprovalStatus.PENDING for a in self.store.approvals_for_goal(goal_id)):raise ValueError('pending approvals must be resolved before replanning')
        context=self.gen1.retrieve_context(goal.user_request,goal.context_requirements);capabilities=list(self.gen1.health().get('tools',[]))
        minimal={'source':context.get('source'),'rendered':str(context.get('rendered',''))[:6000],'capabilities':capabilities,'deadline':goal.deadline,'constraints':goal.constraints}
        proposal,provenance=self.planner.propose(goal,minimal,capabilities);validator=PlanValidator(set(capabilities),self.policy);plan,decisions=validator.validate(proposal,subject='user',timestamp=now())
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
        run=TaskRun(uuid.uuid4().hex,goal_id,None,[],[],[x.step_id for x in plan.steps],[],[],[],now(),now(),goal.deadline,'RUNNING',uuid.uuid4().hex);self.store.save_task_run(run);self.store.save_goal(goal);self.store.event(goal_id,'replanned',{'old_plan_id':old_plan.plan_id,'new_plan_id':plan.plan_id},now())
        return self.resume(goal_id)
    def _approval_for(self,goal_id,step_id):
        items=[a for a in self.store.approvals_for_goal(goal_id) if a.step_id==step_id and a.status in {ApprovalStatus.PENDING,ApprovalStatus.APPROVED,ApprovalStatus.REJECTED}]
        return items[-1] if items else None
    def decide_approval(self,approval_id:str,decision:str,*,actor:str='user'):
        approval=self.store.load_approval(approval_id)
        if approval.status!=ApprovalStatus.PENDING:raise ValueError('approval is not pending')
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
        goal.status=GoalStatus.CANCELLED;run.status='CANCELLED';run.current_step=None;self.store.cancel_pending_approvals(goal_id,now());self.store.event(goal_id,'goal_cancelled',{},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
    def resume(self,goal_id):
        goal=self.store.load_goal(goal_id);plan=self.store.load_plan(goal.plan_id);run=self.store.load_task_run_for_goal(goal_id)
        if goal.status in {GoalStatus.COMPLETED,GoalStatus.CANCELLED}:return self.report(goal,plan,run)
        if self._deadline_expired(goal.deadline):
            goal.status=GoalStatus.BLOCKED;run.status='DEADLINE_EXPIRED';self.store.event(goal_id,'deadline_expired',{'deadline':goal.deadline},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
        iterations=0
        for step in plan.steps:
            if step.status==StepStatus.VERIFIED:continue
            if step.status==StepStatus.WAITING and run.status=='WAITING_FOR_GEN1_APPROVAL':
                output=(step.result or {}).get('output',{});approval_id=output.get('proposal_id') if isinstance(output,dict) else None
                status_fn=getattr(self.gen1,'approval_status',None)
                if approval_id and callable(status_fn):
                    state=status_fn(approval_id,step.preferred_tool);status=state.get('status')
                    self.store.event(goal_id,'gen1_approval_reconciled',{'approval_id':approval_id,'status':status,'verified':bool(state.get('verified'))},now())
                    if status=='APPROVED' and state.get('verified'):
                        step.status=StepStatus.VERIFIED;step.result['verification']=state
                        if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
                        run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];run.status='RUNNING';self._persist(goal,plan,run);continue
                    if status in {'REJECTED','EXPIRED','CANCELLED'}:
                        step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
                    goal.status=GoalStatus.WAITING;self._persist(goal,plan,run);return self.report(goal,plan,run)
                goal.status=GoalStatus.WAITING;self._persist(goal,plan,run);return self.report(goal,plan,run)
            if any(next(x for x in plan.steps if x.step_id==d).status!=StepStatus.VERIFIED for d in step.dependencies):continue
            if iterations>=self.max_iterations:goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            iterations+=1
            permission,risk=self.policy.evaluate(step.preferred_tool,'user',step.description,now())
            if permission.effect==PermissionEffect.DENY:
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            if permission.effect==PermissionEffect.REQUIRE_APPROVAL:
                approval=self._approval_for(goal_id,step.step_id)
                if approval is None:
                    approval=Approval(uuid.uuid4().hex,goal_id,run.task_run_id,step.step_id,step.description,step.preferred_tool,risk.level,now(),None,ApprovalStatus.PENDING,step.description)
                    self.store.save_approval(approval);run.approvals.append(approval.approval_id);self.store.event(goal_id,'approval_required',{'approval_id':approval.approval_id,'step_id':step.step_id},now())
                if approval.status==ApprovalStatus.PENDING:
                    step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_APPROVAL';self._persist(goal,plan,run);return self.report(goal,plan,run)
                if approval.status==ApprovalStatus.REJECTED:
                    step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self._persist(goal,plan,run);return self.report(goal,plan,run)
            if step.attempts>step.retry_limit:
                step.status=StepStatus.BLOCKED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';break
            goal.status=GoalStatus.EXECUTING;step.status=StepStatus.EXECUTING;step.attempts+=1;run.current_step=step.step_id;self._persist(goal,plan,run)
            obs=self.gen1.invoke(step.preferred_tool,step.arguments);step.result={'output':obs.output,'verification':obs.verification};self.store.event(goal_id,'tool_observed',{'tool':step.preferred_tool,'ok':obs.ok},now())
            if not obs.ok:
                step.status=StepStatus.FAILED
                if step.step_id not in run.failed_steps:run.failed_steps.append(step.step_id)
                goal.status=GoalStatus.WAITING if step.attempts<=step.retry_limit else GoalStatus.BLOCKED;run.status=goal.status.value;self._persist(goal,plan,run);return self.report(goal,plan,run)
            goal.status=GoalStatus.VERIFYING
            if not obs.verification.get('verified'):
                step.status=StepStatus.FAILED;goal.status=GoalStatus.BLOCKED;run.status='BLOCKED';self.store.event(goal_id,'verification_failed',obs.verification,now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            if obs.requires_approval:
                step.status=StepStatus.WAITING;goal.status=GoalStatus.WAITING;run.status='WAITING_FOR_GEN1_APPROVAL'
                if obs.approval_id and obs.approval_id not in run.approvals:run.approvals.append(obs.approval_id)
                self.store.event(goal_id,'gen1_approval_required',{'approval_id':obs.approval_id,'tool':step.preferred_tool},now());self._persist(goal,plan,run);return self.report(goal,plan,run)
            step.status=StepStatus.VERIFIED
            if step.step_id not in run.completed_steps:run.completed_steps.append(step.step_id)
            run.pending_steps=[x for x in run.pending_steps if x!=step.step_id];self.store.event(goal_id,'step_verified',{'step_id':step.step_id},now())
        self._evaluate_goal(goal,plan)
        if all(c.status==CriterionStatus.SATISFIED for c in self.store.criteria_for_goal(goal_id)) and all(s.status==StepStatus.VERIFIED for s in plan.steps):
            goal.status=GoalStatus.COMPLETED;run.status='COMPLETED';run.current_step=None;self.store.event(goal_id,'goal_completed',{'authority':'deterministic_goal_evaluator'},now())
        elif goal.status not in {GoalStatus.BLOCKED,GoalStatus.WAITING}:goal.status=GoalStatus.WAITING;run.status='WAITING'
        self._persist(goal,plan,run);return self.report(goal,plan,run)
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
        if goal.status==GoalStatus.COMPLETED:text='Completed. Every required step and goal-level success criterion was independently verified.'
        elif pending:text=f'Waiting for your approval before continuing: {pending[-1].approval_id}.'
        elif goal.status==GoalStatus.BLOCKED:text='Blocked. I did not mark the goal complete because policy, execution, or verification remains unresolved.'
        else:text='Work is not complete yet. Verified progress is persisted and can be resumed.'
        gen1_approvals=[]
        if run.status=='WAITING_FOR_GEN1_APPROVAL':
            for step in plan.steps:
                output=(step.result or {}).get('output',{})
                if step.status==StepStatus.WAITING and isinstance(output,dict):
                    aid=output.get('proposal_id') or output.get('approval_id')
                    if isinstance(aid,str):gen1_approvals.append(aid)
        return {'goal_id':goal.goal_id,'task_run_id':run.task_run_id,'trace_id':run.trace_id,'status':goal.status.value,'text':text,'checked':checked,'verified':verified,'approvals':[a.approval_id for a in pending],'gen1_approvals':gen1_approvals,'model_provenance':self.store.provenance_for_goal(goal.goal_id),'criteria':[c.to_dict() for c in self.store.criteria_for_goal(goal.goal_id)]}
