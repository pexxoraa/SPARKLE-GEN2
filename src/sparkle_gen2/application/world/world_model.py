from __future__ import annotations
import uuid
from dataclasses import asdict, dataclass, field
import hashlib,json
from datetime import datetime, timezone
from ...core_time import now

ENTITY_KINDS={'person','project','document','task','email','meeting','decision','device','robot','experiment','location','event','resource'}
RELATION_TYPES={'contains','depends_on','assigned_to','owns','mentions','scheduled_with','produced_by','related_to','controls','uses','belongs_to','references'}

@dataclass(slots=True)
class WorldNode:
    node_id:str
    kind:str
    state:dict
    observed_at:str
    provenance:dict=field(default_factory=dict)
    epistemic_state:str='observed'
    confidence:float=1.0
    conflicts:list[dict]=field(default_factory=list)
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class WorldEdge:
    edge_id:str
    source:str
    relation:str
    target:str
    observed_at:str
    provenance:dict=field(default_factory=dict)
    epistemic_state:str='observed'
    confidence:float=1.0
    def to_dict(self): return asdict(self)

class WorldModel:
    def __init__(self,store=None):
        self.store=store;self.nodes={};self.edges=[]
        if store is not None:self._restore()
    def _restore(self):
        self.nodes={d['node_id']:WorldNode(**d) for d in self.store.world_nodes()}
        self.edges=[WorldEdge(**d) for d in self.store.world_edges()]
    def observe(self,node_id,kind,state,provenance=None,*,observed_at=None,reject_older=False,epistemic_state='observed',confidence=1.0):
        if not node_id or not kind:raise ValueError('node identity and kind required')
        if kind not in ENTITY_KINDS:raise ValueError('unsupported world entity kind')
        provenance=dict(provenance or {'source':'unknown'});stamp=observed_at or now();datetime.fromisoformat(stamp.replace('Z','+00:00'));epistemic_state=str(epistemic_state).lower();confidence=float(confidence)
        if epistemic_state not in {'observed','inferred','predicted'}:raise ValueError('invalid epistemic state')
        if not 0.0<=confidence<=1.0:raise ValueError('world confidence out of range')
        if reject_older and node_id in self.nodes:
            old=datetime.fromisoformat(self.nodes[node_id].observed_at.replace('Z','+00:00'));new=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if old.tzinfo is None:old=old.replace(tzinfo=timezone.utc)
            if new.tzinfo is None:new=new.replace(tzinfo=timezone.utc)
            if new<old:return self.nodes[node_id]
        conflicts=[]
        if node_id in self.nodes:
            previous=self.nodes[node_id];conflicts=list(getattr(previous,'conflicts',[]) or [])
            if previous.state!=dict(state):
                provenance=provenance|{'supersedes_observation':previous.observed_at}
                previous_source=str((previous.provenance or {}).get('source','unknown'));incoming_source=str(provenance.get('source','unknown'))
                if previous_source!=incoming_source:
                    def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                    conflict_id=hashlib.sha256(f'{node_id}|{previous.observed_at}|{stamp}|{digest(previous.state)}|{digest(dict(state))}'.encode()).hexdigest()[:32]
                    if not any(x.get('conflict_id')==conflict_id for x in conflicts):
                        conflicts.append({'conflict_id':conflict_id,'previous_state_sha256':digest(previous.state),'incoming_state_sha256':digest(dict(state)),'previous_source':previous_source[:160],'incoming_source':incoming_source[:160],'detected_at':stamp,'resolved':False})
                        conflicts=conflicts[-50:]
        n=WorldNode(node_id,kind,dict(state),stamp,provenance,epistemic_state,confidence,conflicts);self.nodes[node_id]=n
        if self.store is not None:self.store.save_world_node(n)
        return n
    def infer(self,node_id,kind,state,provenance=None,*,confidence=0.5,observed_at=None):return self.observe(node_id,kind,state,provenance,observed_at=observed_at,epistemic_state='inferred',confidence=confidence)
    def predict(self,node_id,kind,state,provenance=None,*,confidence=0.5,observed_at=None):return self.observe(node_id,kind,state,provenance,observed_at=observed_at,epistemic_state='predicted',confidence=confidence)
    def relate(self,source,relation,target,provenance=None,*,epistemic_state='observed',confidence=1.0):
        if source not in self.nodes or target not in self.nodes: raise KeyError('unknown node')
        if not relation:raise ValueError('relation required')
        if relation not in RELATION_TYPES:raise ValueError('unsupported world relation type')
        epistemic_state=str(epistemic_state).lower();confidence=float(confidence)
        if epistemic_state not in {'observed','inferred','predicted'}:raise ValueError('invalid epistemic state')
        if not 0.0<=confidence<=1.0:raise ValueError('world confidence out of range')
        e=WorldEdge(uuid.uuid4().hex,source,relation,target,now(),dict(provenance or {'source':'derived'}),epistemic_state,confidence);self.edges.append(e)
        if self.store is not None:self.store.save_world_edge(e)
        return e
    def contradictions(self,node_id,*,include_resolved=False):
        if node_id not in self.nodes:raise KeyError(node_id)
        rows=list(getattr(self.nodes[node_id],'conflicts',[]) or [])
        return rows if include_resolved else [x for x in rows if not x.get('resolved')]
    def resolve_contradiction(self,node_id,conflict_id,state,provenance=None,*,confidence=1.0):
        if node_id not in self.nodes:raise KeyError(node_id)
        node=self.nodes[node_id];rows=list(getattr(node,'conflicts',[]) or []);target=next((x for x in rows if x.get('conflict_id')==conflict_id),None)
        if target is None:raise KeyError(conflict_id)
        if target.get('resolved'):return node
        p=dict(provenance or {})
        if not p.get('source'):raise ValueError('conflict resolution provenance source required')
        target['resolved']=True;target['resolved_at']=now();target['resolution_source']=str(p['source'])[:160]
        updated=self.observe(node_id,node.kind,dict(state),p|{'resolved_conflict_id':conflict_id},epistemic_state='observed',confidence=confidence)
        updated.conflicts=rows
        if self.store is not None:self.store.save_world_node(updated)
        return updated
    def upsert_relation(self,source,relation,target,provenance=None,*,epistemic_state='observed',confidence=1.0):
        existing=next((e for e in self.edges if e.source==source and e.relation==relation and e.target==target),None)
        if existing is None:return self.relate(source,relation,target,provenance,epistemic_state=epistemic_state,confidence=confidence)
        p=dict(provenance or {})
        if not p.get('source'):raise ValueError('relationship provenance source required')
        existing.observed_at=now();existing.provenance=p;existing.epistemic_state=str(epistemic_state).lower();existing.confidence=float(confidence)
        if existing.epistemic_state not in {'observed','inferred','predicted'} or not 0.0<=existing.confidence<=1.0:raise ValueError('invalid relationship epistemic state or confidence')
        if self.store is not None:self.store.save_world_edge(existing)
        return existing
    def query(self,*,kind=None,relation=None,source=None,target=None,max_age_seconds=None,limit=100):
        if not 1<=int(limit)<=500:raise ValueError('query limit out of range')
        nodes=[]
        for n in self.nodes.values():
            if kind is not None and n.kind!=kind:continue
            age=self.freshness(n.node_id)
            if max_age_seconds is not None and age>float(max_age_seconds):continue
            nodes.append(n.to_dict()|{'age_seconds':age,'unresolved_conflicts':len([x for x in n.conflicts if not x.get('resolved')])})
            if len(nodes)>=limit:break
        edges=[]
        for e in self.edges:
            if relation is not None and e.relation!=relation:continue
            if source is not None and e.source!=source:continue
            if target is not None and e.target!=target:continue
            edges.append(e.to_dict())
            if len(edges)>=limit:break
        return {'nodes':nodes,'edges':edges}

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
