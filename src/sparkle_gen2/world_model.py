from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from .core_time import now

ENTITY_KINDS={'person','project','document','task','email','meeting','decision','device','robot','experiment','location','event','resource'}
RELATION_TYPES={'contains','depends_on','assigned_to','owns','mentions','scheduled_with','produced_by','related_to','controls','uses','belongs_to','references'}

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
    edge_id:str
    source:str
    relation:str
    target:str
    observed_at:str
    provenance:dict=field(default_factory=dict)
    def to_dict(self): return asdict(self)

class WorldModel:
    def __init__(self,store=None):
        self.store=store;self.nodes={};self.edges=[]
        if store is not None:self._restore()
    def _restore(self):
        self.nodes={d['node_id']:WorldNode(**d) for d in self.store.world_nodes()}
        self.edges=[WorldEdge(**d) for d in self.store.world_edges()]
    def observe(self,node_id,kind,state,provenance=None):
        if not node_id or not kind:raise ValueError('node identity and kind required')
        if kind not in ENTITY_KINDS:raise ValueError('unsupported world entity kind')
        provenance=dict(provenance or {'source':'unknown'})
        n=WorldNode(node_id,kind,dict(state),now(),provenance);self.nodes[node_id]=n
        if self.store is not None:self.store.save_world_node(n)
        return n
    def relate(self,source,relation,target,provenance=None):
        if source not in self.nodes or target not in self.nodes: raise KeyError('unknown node')
        if not relation:raise ValueError('relation required')
        if relation not in RELATION_TYPES:raise ValueError('unsupported world relation type')
        e=WorldEdge(uuid.uuid4().hex,source,relation,target,now(),dict(provenance or {'source':'derived'}));self.edges.append(e)
        if self.store is not None:self.store.save_world_edge(e)
        return e
    def freshness(self,node_id,*,at=None):
        node=self.nodes[node_id];instant=at or datetime.now(timezone.utc)
        observed=datetime.fromisoformat(node.observed_at)
        if observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
        return max(0.0,(instant-observed).total_seconds())
    def neighbors(self,node_id,*,relation=None,max_age_seconds=None):
        if node_id not in self.nodes:raise KeyError(node_id)
        out=[]
        for edge in self.edges:
            if relation is not None and edge.relation!=relation:continue
            other=None
            if edge.source==node_id:other=edge.target
            elif edge.target==node_id:other=edge.source
            if other is None:continue
            age=self.freshness(other)
            if max_age_seconds is not None and age>max_age_seconds:continue
            out.append({'edge':edge.to_dict(),'node':self.nodes[other].to_dict(),'age_seconds':age})
        return out
    def fresh_nodes(self,*,kind=None,max_age_seconds=300):
        if max_age_seconds<0:raise ValueError('max_age_seconds must be non-negative')
        out=[]
        for node in self.nodes.values():
            if kind is not None and node.kind!=kind:continue
            age=self.freshness(node.node_id)
            if age<=max_age_seconds:out.append(node.to_dict()|{'age_seconds':age})
        return out
    def snapshot(self):
        return {'nodes':[n.to_dict()|{'age_seconds':self.freshness(n.node_id)} for n in self.nodes.values()],'edges':[e.to_dict() for e in self.edges]}
