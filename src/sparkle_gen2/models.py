from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

class GoalStatus(StrEnum):
    CREATED="CREATED"; UNDERSTANDING="UNDERSTANDING"; PLANNED="PLANNED"; AUTHORIZED="AUTHORIZED"
    EXECUTING="EXECUTING"; WAITING="WAITING"; VERIFYING="VERIFYING"; BLOCKED="BLOCKED"
    COMPLETED="COMPLETED"; FAILED="FAILED"; CANCELLED="CANCELLED"

class StepStatus(StrEnum):
    PENDING="PENDING"; EXECUTING="EXECUTING"; WAITING="WAITING"; VERIFIED="VERIFIED"; FAILED="FAILED"; BLOCKED="BLOCKED"

@dataclass(slots=True)
class Goal:
    goal_id:str; user_request:str; normalized_objective:str
    constraints:list[str]=field(default_factory=list); priority:int=5; deadline:str|None=None
    success_criteria:list[str]=field(default_factory=list); risk_level:str="LOW"
    context_requirements:list[str]=field(default_factory=list); status:GoalStatus=GoalStatus.CREATED
    plan_id:str|None=None; parent_goal_id:str|None=None; created_at:str=""; updated_at:str=""
    def to_dict(self)->dict[str,Any]:
        d=asdict(self); d["status"]=self.status.value; return d

@dataclass(slots=True)
class PlanStep:
    step_id:str; description:str; dependencies:list[str]; required_capabilities:list[str]
    preferred_tool:str; preferred_model_capability:str; risk:str; authorization_requirement:str
    timeout_seconds:int; retry_limit:int; success_criteria:list[str]; verification_method:str
    rollback_strategy:str|None; arguments:dict[str,Any]=field(default_factory=dict)
    status:StepStatus=StepStatus.PENDING; attempts:int=0; result:dict[str,Any]|None=None
    def to_dict(self)->dict[str,Any]:
        d=asdict(self); d["status"]=self.status.value; return d

@dataclass(slots=True)
class Plan:
    plan_id:str; goal_id:str; steps:list[PlanStep]; created_at:str
    def to_dict(self)->dict[str,Any]:
        return {"plan_id":self.plan_id,"goal_id":self.goal_id,"created_at":self.created_at,"steps":[s.to_dict() for s in self.steps]}

@dataclass(slots=True)
class TaskRun:
    task_run_id:str; goal_id:str; current_step:str|None; completed_steps:list[str]; failed_steps:list[str]
    pending_steps:list[str]; artifacts:list[str]; approvals:list[str]; events:list[dict[str,Any]]
    started_at:str; updated_at:str; deadline:str|None; status:str
    def to_dict(self)->dict[str,Any]: return asdict(self)
