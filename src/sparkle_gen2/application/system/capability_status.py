from __future__ import annotations
from dataclasses import asdict,dataclass

VALID={'DESIGNED','IMPLEMENTED','TESTED','INTEGRATED','CONFIGURED','CONNECTED','LIVE_VERIFIED','EXTERNALLY_BLOCKED','DEFERRED'}
@dataclass(slots=True)
class CapabilityState:
    capability:str
    status:str
    evidence:str
    dependency:str|None=None
    limitation:str|None=None
    def __post_init__(self):
        if self.status not in VALID:raise ValueError('invalid capability status')
    def to_dict(self):return asdict(self)
class CapabilityMatrix:
    def __init__(self):self.items={}
    def set(self,state:CapabilityState):self.items[state.capability]=state;return state
    def unresolved(self):return [s for s in self.items.values() if s.status not in {'LIVE_VERIFIED','EXTERNALLY_BLOCKED','DEFERRED'}]
    def summary(self):return [self.items[k].to_dict() for k in sorted(self.items)]
