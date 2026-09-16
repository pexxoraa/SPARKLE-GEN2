from __future__ import annotations
from dataclasses import asdict, dataclass, field
from .core_time import now

@dataclass(slots=True)
class WorldNode:
    node_id:str
    kind:str
    state:dict
    observed_at:str
    provenance:dict=field(default_factory=dict)
    def to_dict(self): return asdict(self)
@dataclass(slots=True)
class WorldEdge:
    source:str
    relation:str
    target:str

class WorldModel:
    def __init__(self): self.nodes={};self.edges=[]
    def observe(self,node_id,kind,state,provenance=None):
        n=WorldNode(node_id,kind,dict(state),now(),provenance or {});self.nodes[node_id]=n;return n
    def relate(self,source,relation,target):
        if source not in self.nodes or target not in self.nodes: raise KeyError('unknown node')
        e=WorldEdge(source,relation,target);self.edges.append(e);return e
    def snapshot(self):return {'nodes':[n.to_dict() for n in self.nodes.values()],'edges':[asdict(e) for e in self.edges]}
