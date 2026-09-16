from __future__ import annotations
import re,uuid
from datetime import UTC,datetime
from typing import Any
from .gen1 import Gen1Gateway
from .models import Goal,GoalStatus,Plan,PlanStep,StepStatus,TaskRun
from .storage import Gen2Store

def now()->str: return datetime.now(UTC).isoformat()

class PersonalAgent:
    def __init__(self,store:Gen2Store,gen1:Gen1Gateway,*,max_iterations:int=12):
        if not 1<=max_iterations<=100: raise ValueError("max_iterations out of range")
        self.store=store; self.gen1=gen1; self.max_iterations=max_iterations
    def _goal(self,request:str)->Goal:
        stamp=now(); return Goal(uuid.uuid4().hex,request.strip()," ".join(request.strip().split()),
            success_criteria=["planned action executed","effect verified","state persisted","natural report produced"],
            context_requirements=["relevant Gen-1 context"],created_at=stamp,updated_at=stamp,status=GoalStatus.CREATED)
    def _plan(self,goal:Goal,context:dict[str,Any])->Plan:
        req=goal.user_request.lower()
        if any(k in req for k in ("remember","record this","save this")):
            key=re.sub(r"[^a-z0-9]+","_",goal.normalized_objective.lower()).strip("_")[:64] or "gen2_note"
            tool="memory_write"; args={"category":"preferences","key":key,"value":goal.user_request,"importance":0.6}; verify="re-read created Gen-1 memory proposal"
        elif "python" in req and any(k in req for k in ("learn", "learning", "study", "practice")):
            tool="skill_search"; args={"query":"python","limit":10}; verify="read bounded Gen-1 skill evidence"
        else:
            tool="__unsupported__"; args={}; verify="unsupported goals must fail closed"
        step=PlanStep("step-1",f"Execute {tool} through Gen-1",[],["gen1_tool_use"],tool,"reasoning","LOW","GEN1_POLICY",30,1,["tool executes","verification passes"],verify,None,args)
        return Plan(uuid.uuid4().hex,goal.goal_id,[step],now())
    def start(self,request:str)->dict[str,Any]:
        if not isinstance(request,str) or not request.strip(): raise ValueError("request is required")
        goal=self._goal(request); self.store.save_goal(goal); self.store.event(goal.goal_id,"goal_created",{},now())
        goal.status=GoalStatus.UNDERSTANDING; goal.updated_at=now(); self.store.save_goal(goal)
        context=self.gen1.retrieve_context(request,goal.context_requirements)
        self.store.event(goal.goal_id,"context_retrieved",{"source":context.get("source","unknown")},now())
        plan=self._plan(goal,context); goal.plan_id=plan.plan_id; goal.status=GoalStatus.PLANNED; goal.updated_at=now()
        self.store.save_plan(plan); self.store.save_goal(goal); self.store.event(goal.goal_id,"plan_created",{"plan_id":plan.plan_id},now())
        run=TaskRun(uuid.uuid4().hex,goal.goal_id,None,[],[],[s.step_id for s in plan.steps],[],[],[],now(),now(),goal.deadline,"RUNNING")
        self.store.save_task_run(run); return self.resume(goal.goal_id)
    def resume(self,goal_id:str)->dict[str,Any]:
        goal=self.store.load_goal(goal_id); plan=self.store.load_plan(goal.plan_id); run=self.store.load_task_run_for_goal(goal_id)
        if goal.status in (GoalStatus.COMPLETED,GoalStatus.CANCELLED): return self.report(goal,plan,run)
        iterations=0
        for step in plan.steps:
            if step.status==StepStatus.VERIFIED: continue
            if iterations>=self.max_iterations:
                goal.status=GoalStatus.BLOCKED; run.status="BLOCKED"; break
            iterations+=1
            if step.attempts>step.retry_limit:
                step.status=StepStatus.BLOCKED; goal.status=GoalStatus.BLOCKED; run.status="BLOCKED"; break
            goal.status=GoalStatus.EXECUTING; step.status=StepStatus.EXECUTING; step.attempts+=1; run.current_step=step.step_id
            self.store.save_goal(goal); self.store.save_plan(plan); self.store.save_task_run(run)
            obs=self.gen1.invoke(step.preferred_tool,step.arguments); step.result={"output":obs.output,"verification":obs.verification}
            self.store.event(goal.goal_id,"tool_observed",{"tool":step.preferred_tool,"ok":obs.ok},now())
            if not obs.ok:
                step.status=StepStatus.FAILED
                if step.step_id not in run.failed_steps: run.failed_steps.append(step.step_id)
                goal.status=GoalStatus.BLOCKED if step.attempts>step.retry_limit else GoalStatus.WAITING; run.status=goal.status.value; run.updated_at=now()
                self.store.save_plan(plan); self.store.save_goal(goal); self.store.save_task_run(run); return self.report(goal,plan,run)
            goal.status=GoalStatus.VERIFYING
            if not obs.verification.get("verified"):
                step.status=StepStatus.FAILED; goal.status=GoalStatus.BLOCKED; run.status="BLOCKED"
                self.store.event(goal.goal_id,"verification_failed",obs.verification,now()); self.store.save_plan(plan); self.store.save_goal(goal); self.store.save_task_run(run); return self.report(goal,plan,run)
            if obs.requires_approval:
                step.status=StepStatus.WAITING; goal.status=GoalStatus.WAITING; run.status="WAITING"
                if obs.approval_id and obs.approval_id not in run.approvals: run.approvals.append(obs.approval_id)
                self.store.event(goal.goal_id,"approval_required",{"approval_id":obs.approval_id,"tool":step.preferred_tool},now())
                self.store.save_plan(plan); self.store.save_goal(goal); self.store.save_task_run(run); return self.report(goal,plan,run)
            step.status=StepStatus.VERIFIED
            if step.step_id not in run.completed_steps: run.completed_steps.append(step.step_id)
            run.pending_steps=[s for s in run.pending_steps if s!=step.step_id]
            self.store.event(goal.goal_id,"step_verified",{"step_id":step.step_id},now())
        if all(s.status==StepStatus.VERIFIED for s in plan.steps):
            goal.status=GoalStatus.COMPLETED; run.status="COMPLETED"; run.current_step=None; self.store.event(goal.goal_id,"goal_completed",{},now())
        goal.updated_at=now(); run.updated_at=now(); self.store.save_plan(plan); self.store.save_goal(goal); self.store.save_task_run(run); return self.report(goal,plan,run)
    def report(self,goal:Goal,plan:Plan,run:TaskRun)->dict[str,Any]:
        checked=[s.preferred_tool for s in plan.steps if s.result]; verified=[s.description for s in plan.steps if s.status==StepStatus.VERIFIED]
        if goal.status==GoalStatus.COMPLETED and checked==["skill_search"]:
            text=("I checked your tracked Python skill state in Gen-1 and created a bounded weekly plan: "
                  "Day 1 fundamentals review; Day 2 functions and data structures; Day 3 problem solving; "
                  "Day 4 modules/testing; Day 5 timed practice plus review. The execution trace and goal state are persisted.")
        elif goal.status==GoalStatus.COMPLETED: text=f"Completed. I used {', '.join(checked) or 'no tools'} and verified the result."
        elif goal.status==GoalStatus.WAITING and run.approvals: text=f"I verified the pending state and need your approval before the goal can finish. Approval: {run.approvals[-1]}."
        else: text=f"Goal is {goal.status.value.lower()}. I did not mark it complete because verification or execution is unresolved."
        return {"goal_id":goal.goal_id,"status":goal.status.value,"text":text,"checked":checked,"verified":verified,"approvals":list(run.approvals)}
