from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any
from ...domain.contracts.tool_protocol import ToolDefinition,ToolMetadata,PermissionMetadata,RiskMetadata,VerificationMetadata

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

    @classmethod
    def from_health(cls, health, policy, *, timestamp, agent_ids=('personal',)):
        """Build executable descriptors from the available adapter contracts."""
        catalog=cls()
        definitions={d['name']:d for d in health.get('tool_definitions',[]) if isinstance(d,dict) and d.get('name')}
        native=set(health.get('native_tools',[]))
        for identity in sorted(set(health.get('tools',[]))):
            permission,risk=policy.evaluate(identity,'user','exact_plan_step',timestamp)
            if permission.effect.value=='DENY':continue
            definition=definitions.get(identity,{})
            envelope=ToolDefinition(identity,identity,definition.get('description','Native bounded '+identity),
                identity.split('_',1)[0],dict(definition.get('parameters') or {'type':'object'}),
                {'type':'object','required':['success','data','verification']},
                PermissionMetadata(permission.effect.value),
                RiskMetadata(risk.level.value,risk.rationale,permission.effect.value!='ALLOW'),
                VerificationMetadata(),ToolMetadata('gen1_gateway' if identity in native else 'gen2_tool_dispatch',True,tuple(agent_ids)))
            catalog.register(CapabilityDescriptor(identity,'1',identity,envelope.inputs,envelope.outputs,
                envelope.permission.authentication,permission.effect.value,risk.level.value,30,
                'bounded_read_retry' if permission.effect.value=='ALLOW' else 'exact_approval_no_blind_replay',
                envelope.verification.strategy,None,metadata={'tool_definition':envelope.to_dict(),'execution_handler':envelope.metadata.handler}))
        return catalog

    def definitions(self):
        return [x.metadata['tool_definition'] for x in self.list()]
