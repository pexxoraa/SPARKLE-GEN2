from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass
from .core_time import now

@dataclass(slots=True)
class Session:
    session_id:str
    active_goal_id:str|None
    created_at:str
    updated_at:str
    status:str='ACTIVE'
    def to_dict(self): return asdict(self)

class SessionService:
    def __init__(self,store): self.store=store
    def create(self,goal_id=None):
        s=Session(uuid.uuid4().hex,goal_id,now(),now());self.store.save_session(s);return s
    def attach_goal(self,session_id,goal_id):
        s=self.store.load_session(session_id);s.active_goal_id=goal_id;s.updated_at=now();self.store.save_session(s);return s
    def recover(self,session_id): return self.store.load_session(session_id)
