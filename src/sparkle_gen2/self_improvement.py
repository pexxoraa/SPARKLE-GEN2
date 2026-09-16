from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass

@dataclass(slots=True)
class ImprovementCandidate:
    candidate_id:str
    capability:str
    design:str
    tests_passed:bool=False
    reviewed:bool=False
    approved:bool=False
    status:str='DESIGNED'
    def to_dict(self):return asdict(self)
class ControlledImprovementPipeline:
    def __init__(self):self.items={}
    def propose(self,capability,design):
        c=ImprovementCandidate(uuid.uuid4().hex,capability,design);self.items[c.candidate_id]=c;return c
    def record_tests(self,cid,passed):
        c=self.items[cid];c.tests_passed=bool(passed);c.status='TESTED' if passed else 'FAILED';return c
    def review(self,cid,accepted):
        c=self.items[cid];c.reviewed=bool(accepted);c.status='REVIEWED' if accepted else 'REJECTED';return c
    def approve(self,cid,actor):
        c=self.items[cid]
        if actor!='human':raise PermissionError('human_approval_required')
        if not c.tests_passed or not c.reviewed:raise ValueError('candidate_not_ready')
        c.approved=True;c.status='APPROVED';return c
    def install(self,cid):
        c=self.items[cid]
        if not c.approved:raise PermissionError('approval_required')
        c.status='INSTALLED';return c
