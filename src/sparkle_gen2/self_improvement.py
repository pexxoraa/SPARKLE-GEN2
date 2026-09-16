from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass,field

@dataclass(slots=True)
class ImprovementCandidate:
    candidate_id:str;capability:str;design:str;gap:str='';implementation:dict=field(default_factory=dict)
    tests_passed:bool=False;reviewed:bool=False;approved:bool=False;status:str='DESIGNED'
    def to_dict(self):return asdict(self)
class ControlledImprovementPipeline:
    def __init__(self,store=None,installer=None):
        self.store=store;self.installer=installer;self.items={}
        if store is not None:
            for d in store.improvement_candidates():self.items[d['candidate_id']]=ImprovementCandidate(**d)
    def _save(self,c):
        self.items[c.candidate_id]=c
        if self.store is not None:self.store.save_improvement_candidate(c)
        return c
    def discover(self,capability,gap):
        if not str(gap).strip():raise ValueError('gap required')
        return {'capability':capability,'gap':str(gap)}
    def propose(self,capability,design,*,gap=''):
        if not str(design).strip():raise ValueError('design required')
        return self._save(ImprovementCandidate(uuid.uuid4().hex,capability,design,str(gap)))
    def implement(self,cid,implementation):
        c=self.items[cid]
        if not isinstance(implementation,dict) or not implementation:raise ValueError('implementation evidence required')
        c.implementation=dict(implementation);c.status='IMPLEMENTED';return self._save(c)
    def record_tests(self,cid,passed):
        c=self.items[cid]
        if not c.implementation:raise ValueError('implementation_required')
        c.tests_passed=bool(passed);c.status='TESTED' if passed else 'FAILED';return self._save(c)
    def review(self,cid,accepted):
        c=self.items[cid];c.reviewed=bool(accepted);c.status='REVIEWED' if accepted else 'REJECTED';return self._save(c)
    def approve(self,cid,actor):
        c=self.items[cid]
        if actor!='human':raise PermissionError('human_approval_required')
        if not c.tests_passed or not c.reviewed:raise ValueError('candidate_not_ready')
        c.approved=True;c.status='APPROVED';return self._save(c)
    def install(self,cid):
        c=self.items[cid]
        if not c.approved:raise PermissionError('approval_required')
        evidence=self.installer(c) if self.installer else {'registered':True}
        if not isinstance(evidence,dict) or evidence.get('registered') is not True:raise RuntimeError('install_verification_failed')
        c.status='INSTALLED';self._save(c);return {'candidate':c,'verification':evidence}
