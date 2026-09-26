from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass,field

@dataclass(slots=True)
class ImprovementCandidate:
    candidate_id:str;capability:str;design:str;gap:str='';implementation:dict=field(default_factory=dict)
    tests_passed:bool=False;reviewed:bool=False;approved:bool=False;status:str='DESIGNED'
    security_reviewed:bool=False;security_passed:bool=False;security_evidence:dict=field(default_factory=dict)
    deployment_verification:dict=field(default_factory=dict);rollback:dict=field(default_factory=dict)
    def to_dict(self):return asdict(self)
class ControlledImprovementPipeline:
    FORBIDDEN_CAPABILITIES=frozenset({'policy_override','approval_bypass','verification_bypass','audit_disable','identity_override','secret_exfiltration'})
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
        if str(capability) in self.FORBIDDEN_CAPABILITIES:raise PermissionError('self_improvement_security_boundary')
        return self._save(ImprovementCandidate(uuid.uuid4().hex,capability,design,str(gap)))
    def implement(self,cid,implementation):
        c=self.items[cid]
        if not isinstance(implementation,dict) or not implementation:raise ValueError('implementation evidence required')
        c.implementation=dict(implementation);c.status='IMPLEMENTED';return self._save(c)
    def record_tests(self,cid,passed):
        c=self.items[cid]
        if not c.implementation:raise ValueError('implementation_required')
        c.tests_passed=bool(passed);c.status='TESTED' if passed else 'FAILED';return self._save(c)
    def record_security(self,cid,passed,evidence):
        c=self.items[cid]
        if not c.tests_passed:raise ValueError('passing_tests_required_before_security_review')
        if not isinstance(evidence,dict) or not evidence:raise ValueError('security evidence required')
        c.security_reviewed=True;c.security_passed=bool(passed);c.security_evidence=dict(evidence);c.status='SECURITY_REVIEWED' if passed else 'SECURITY_FAILED';return self._save(c)
    def review(self,cid,accepted):
        c=self.items[cid];c.reviewed=bool(accepted);c.status='REVIEWED' if accepted else 'REJECTED';return self._save(c)
    def approve(self,cid,actor):
        c=self.items[cid]
        if actor!='human':raise PermissionError('human_approval_required')
        if not c.tests_passed or not c.reviewed or not c.security_reviewed or not c.security_passed:raise ValueError('candidate_not_ready')
        c.approved=True;c.status='APPROVED';return self._save(c)
    def install(self,cid):
        c=self.items[cid]
        if not c.approved:raise PermissionError('approval_required')
        evidence=self.installer(c) if self.installer else {'registered':True,'rollback_available':False,'rollback_reason':'no deployment-specific rollback adapter configured'}
        if not isinstance(evidence,dict) or evidence.get('registered') is not True:raise RuntimeError('install_verification_failed')
        c.deployment_verification=dict(evidence);c.rollback={'available':bool(evidence.get('rollback_available')),'strategy':evidence.get('rollback_strategy'),'reference':evidence.get('rollback_reference'),'reason':evidence.get('rollback_reason')};c.status='INSTALLED';self._save(c);return {'candidate':c,'verification':evidence,'rollback':dict(c.rollback)}
    def rollback_install(self,cid,executor,*,actor='human'):
        c=self.items[cid]
        if actor!='human':raise PermissionError('human_approval_required')
        if c.status!='INSTALLED':raise ValueError('candidate_not_installed')
        if c.rollback.get('available') is not True or not c.rollback.get('strategy'):raise RuntimeError('rollback_unavailable')
        if not callable(executor):raise ValueError('trusted rollback executor required')
        evidence=executor(dict(c.rollback))
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:raise RuntimeError('rollback_verification_failed')
        c.status='ROLLED_BACK';c.rollback=dict(c.rollback)|{'verification':dict(evidence)};self._save(c);return {'candidate':c,'verification':evidence}
