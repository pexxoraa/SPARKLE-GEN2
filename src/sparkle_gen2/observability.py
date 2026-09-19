from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass, field
from .core_time import now

@dataclass(slots=True)
class OperationTrace:
    trace_id:str
    goal_id:str|None
    task_run_id:str|None
    kind:str
    component:str
    status:str
    created_at:str
    correlation:dict=field(default_factory=dict)
    detail:dict=field(default_factory=dict)
    def to_dict(self): return asdict(self)

class TraceRecorder:
    def __init__(self,store=None): self._traces=[];self.store=store
    def record(self,kind,component,status,*,goal_id=None,task_run_id=None,trace_id=None,correlation=None,detail=None):
        t=OperationTrace(trace_id or uuid.uuid4().hex,goal_id,task_run_id,kind,component,status,now(),correlation or {},detail or {})
        if self.store is not None:self.store.save_operation_trace(t)
        else:self._traces.append(t)
        return t
    def list(self,goal_id=None,*,trace_id=None):
        if self.store is not None:return [OperationTrace(**d) for d in self.store.operation_traces(goal_id=goal_id,trace_id=trace_id)]
        return [t for t in self._traces if (goal_id is None or t.goal_id==goal_id) and (trace_id is None or t.trace_id==trace_id)]
