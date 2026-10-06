from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(slots=True)
class CapabilityDescriptor:
    identity:str
    version:str
    capability:str
    input_schema:dict[str,Any]
    output_schema:dict[str,Any]
    authentication:str
    permission:str
    risk:str
    timeout_seconds:int
    idempotency:str
    verification:str
    rollback:str|None
    audit:bool=True
    metadata:dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return asdict(self)

class CapabilityCatalog:
    def __init__(self): self._items={}
    def register(self,descriptor:CapabilityDescriptor):
        if descriptor.identity in self._items: raise ValueError('duplicate capability identity')
        if not 1<=descriptor.timeout_seconds<=600: raise ValueError('invalid timeout')
        if descriptor.risk not in {'LOW','MEDIUM','HIGH','CRITICAL'}: raise ValueError('invalid risk')
        self._items[descriptor.identity]=descriptor
    def get(self,identity): return self._items[identity]
    def list(self): return [self._items[k] for k in sorted(self._items)]
