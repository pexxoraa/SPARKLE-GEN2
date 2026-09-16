from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass
from .core_time import now

TERMINAL={'COMPLETED','FAILED','CANCELLED'}
@dataclass(slots=True)
class BackgroundTask:
    background_id:str
    goal_id:str
    state:str
    created_at:str
    updated_at:str
    max_iterations:int=100
    iterations:int=0
    last_error:str|None=None
    def to_dict(self): return asdict(self)

class BackgroundTaskService:
    def __init__(self,store,agent_factory): self.store=store;self.agent_factory=agent_factory
    def create(self,goal_id,max_iterations=100):
        if not 1<=max_iterations<=1000: raise ValueError('max_iterations out of range')
        t=BackgroundTask(uuid.uuid4().hex,goal_id,'QUEUED',now(),now(),max_iterations);self.store.save_background_task(t);return t
    def pause(self,bid):
        t=self.store.load_background_task(bid)
        if t.state not in TERMINAL:t.state='PAUSED';t.updated_at=now();self.store.save_background_task(t)
        return t
    def cancel(self,bid):
        t=self.store.load_background_task(bid);t.state='CANCELLED';t.updated_at=now();self.store.save_background_task(t);return t
    def resume(self,bid):
        t=self.store.load_background_task(bid)
        if t.state in TERMINAL:return t
        t.state='RUNNING';t.updated_at=now();self.store.save_background_task(t)
        agent=self.agent_factory()
        while t.iterations<t.max_iterations and t.state=='RUNNING':
            result=agent.resume(t.goal_id);t.iterations+=1;t.updated_at=now()
            if result['status']=='COMPLETED':t.state='COMPLETED';break
            if result['status']=='BLOCKED':t.state='BLOCKED';break
            if result.get('approvals'):t.state='WAITING_FOR_APPROVAL';break
            if result['status']=='WAITING':t.state='WAITING';break
        if t.iterations>=t.max_iterations and t.state=='RUNNING':t.state='PAUSED';t.last_error='iteration_budget_exhausted'
        self.store.save_background_task(t);return t
