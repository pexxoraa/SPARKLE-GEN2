from __future__ import annotations
import hashlib,re
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime,timedelta
from ..core_time import now
from ..domain.models import CriterionStatus,GoalStatus,PermissionEffect

_SECRET_PATTERNS=(
    re.compile(r'(?i)\b(password|passwd|secret|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|token|bearer|credential|private[ _-]?key)\b'),
    re.compile(r'\b(?:nvapi|gh[pousr]|sk)-?[A-Za-z0-9_-]{16,}\b'),
    re.compile(r'\b[A-Za-z0-9_+/=-]{32,}\b'),
)

@dataclass(slots=True)
class MemoryCandidate:
    candidate_id:str
    goal_id:str
    task_run_id:str
    trace_id:str
    value:str
    category:str
    memory_key:str
    reason:str
    source:str
    evidence:dict
    confidence:float
    privacy_classification:str
    created_at:str
    state:str='PROPOSED'
    approved_by:str|None=None
    decision_at:str|None=None
    gen1_approval_id:str|None=None
    memory_id:str|None=None
    review_verification:dict=field(default_factory=dict)
    owner_user_id:str='user'
    fingerprint:str=''
    expires_at:str|None=None
    supersedes_candidate_id:str|None=None
    def to_dict(self):return asdict(self)

class MemoryCandidateAnalyzer:
    """Deterministic, conservative completion analysis; never writes memory."""
    _RULES=(
        ('preferences',re.compile(r'(?i)^\s*remember\s+that\s+(i\s+prefer\s+.+?)\s*[.!?]*\s*$'),.99,'explicit durable preference'),
        ('preferences',re.compile(r'(?i)^\s*(i\s+prefer\s+.+?)\s*[.!?]*\s*$'),.95,'explicit durable preference'),
        ('preferences',re.compile(r'(?i)^\s*(my\s+preference\s+is\s+.+?)\s*[.!?]*\s*$'),.95,'explicit durable preference'),
        ('goals',re.compile(r'(?i)^\s*remember\s+that\s+(my\s+goal\s+is\s+.+?)\s*[.!?]*\s*$'),.98,'explicit durable goal'),
        ('decisions',re.compile(r'(?i)^\s*remember\s+that\s+(we\s+decided\s+.+?)\s*[.!?]*\s*$'),.98,'explicit durable decision'),
        ('learning',re.compile(r'(?i)^\s*remember\s+that\s+(i\s+(?:learned|completed|mastered)\s+.+?)\s*[.!?]*\s*$'),.94,'explicit durable learning milestone'),
        ('preferences',re.compile(r'(?i)^\s*remember\s+that\s+(.+?)\s*[.!?]*\s*$'),.92,'explicit user-requested memory'),
    )
    def __init__(self,*,max_candidates=3,max_value_chars=1000):
        if not 1<=int(max_candidates)<=10:raise ValueError('max_candidates out of range')
        if not 64<=int(max_value_chars)<=4000:raise ValueError('max_value_chars out of range')
        self.max_candidates=int(max_candidates);self.max_value_chars=int(max_value_chars)
    @staticmethod
    def _secret(text):return any(p.search(text) for p in _SECRET_PATTERNS)
    @staticmethod
    def _normalize(value):return ' '.join(str(value).split()).strip()
    def analyze(self,goal,run,criteria):
        if goal.status!=GoalStatus.COMPLETED or run.status!='COMPLETED':return []
        criteria=list(criteria)
        if not criteria or any(c.status!=CriterionStatus.SATISFIED for c in criteria):return []
        request=self._normalize(goal.user_request)
        if not request or len(request)>8000 or self._secret(request):return []
        selections=[]
        for category,pattern,confidence,reason in self._RULES:
            match=pattern.fullmatch(request)
            if match:
                value=self._normalize(match.group(1))
                if 4<=len(value)<=self.max_value_chars and not self._secret(value):
                    selections.append((category,value,confidence,reason,'user_statement'))
                break
        # Verified durable outputs are useful even without an explicit "remember" request.
        # Only opaque artifact references are retained; model reasoning and raw output are excluded.
        if not selections:
            for reference in list(run.artifacts)[:self.max_candidates]:
                if isinstance(reference,str) and re.fullmatch(r'artifact:[A-Za-z0-9_-]{1,64}',reference):
                    selections.append(('learning','Verified completed work produced '+reference,.90,'verified durable output','artifact_reference'))
        owner=str(getattr(goal,'user_id','user'))
        candidates=[]
        for category,value,confidence,reason,source in selections[:self.max_candidates]:
            fingerprint=hashlib.sha256(f'{owner}|{category}|{value.casefold()}'.encode()).hexdigest()
            digest=hashlib.sha256(f'{goal.goal_id}|{fingerprint}'.encode()).hexdigest()
            evidence={'goal_status':goal.status.value,'task_status':run.status,
                      'verified_steps':list(run.completed_steps)[:100],
                      'criteria_satisfied':len(criteria),'source_kind':source}
            candidates.append(MemoryCandidate(
                candidate_id='memcand_'+digest[:32],goal_id=goal.goal_id,task_run_id=run.task_run_id,
                trace_id=run.trace_id or '',value=value,category=category,memory_key='completion_'+fingerprint[:20],
                reason=reason,source='verified_completed_goal:'+source,evidence=evidence,
                confidence=confidence,privacy_classification='PERSONAL',created_at=now(),
                owner_user_id=owner,fingerprint=fingerprint,
                expires_at=(datetime.now(UTC)+timedelta(days=90)).isoformat() if category=='goals' else None,
            ))
        return candidates

class MemoryCandidateService:
    """Stages candidates in Gen-2 and delegates authoritative persistence to Gen-1 review."""
    FORBIDDEN_APPROVERS={'model','assistant','nemotron','system','system_cancel'}
    def __init__(self,store,gen1,policy,*,analyzer=None):
        self.store=store;self.gen1=gen1;self.policy=policy;self.analyzer=analyzer or MemoryCandidateAnalyzer()
    @staticmethod
    def expired(candidate):
        if not candidate.expires_at:return False
        try:return datetime.fromisoformat(candidate.expires_at)<=datetime.now(UTC)
        except (ValueError,TypeError):return True
    def analyze_completion(self,goal,run,criteria):
        existing=self.list()
        out=[]
        for candidate in self.analyzer.analyze(goal,run,criteria):
            previous=next((c for c in existing if c.candidate_id==candidate.candidate_id),None)
            if previous is not None:
                out.append(previous);continue
            if any(c.owner_user_id==candidate.owner_user_id and c.fingerprint==candidate.fingerprint and c.state in {'PROPOSED','REVIEW_PENDING','PERSISTED'} and not self.expired(c) for c in existing):continue
            permission,_=self.policy.evaluate('memory_write',candidate.owner_user_id,'completion_memory_proposal',now())
            if permission.effect==PermissionEffect.DENY:continue
            candidate.evidence['policy_effect']=permission.effect.value
            self.store.save_memory_candidate(candidate);out.append(candidate);existing.append(candidate)
        return out
    def list(self,goal_id=None):
        return [MemoryCandidate(**d) for d in self.store.memory_candidates(goal_id=goal_id)]
    def get(self,candidate_id):return MemoryCandidate(**self.store.load_memory_candidate(candidate_id))
    def decide(self,candidate_id,decision,*,actor='user'):
        candidate=self.get(candidate_id)
        if candidate.state!='PROPOSED':raise ValueError('memory candidate is not pending')
        if self.expired(candidate):
            candidate.state='EXPIRED';self.store.save_memory_candidate(candidate);raise ValueError('memory candidate expired')
        if str(actor).strip().lower() in self.FORBIDDEN_APPROVERS or not str(actor).strip():raise PermissionError('human_approval_required')
        if decision not in {'approve','reject'}:raise ValueError('decision must be approve or reject')
        candidate.approved_by=str(actor);candidate.decision_at=now()
        if decision=='reject':
            candidate.state='REJECTED';self.store.save_memory_candidate(candidate);return candidate
        permission,_=self.policy.evaluate('memory_write','user',f'Remember approved completion candidate {candidate.candidate_id}',now())
        if permission.effect==PermissionEffect.DENY:
            candidate.state='BLOCKED';self.store.save_memory_candidate(candidate);raise PermissionError('memory_write_denied')
        if 'memory_write' not in set(self.gen1.health().get('tools',[])):raise RuntimeError('memory_write_unavailable')
        obs=self.gen1.invoke('memory_write',{'category':candidate.category,'key':candidate.memory_key,'value':candidate.value,'importance':candidate.confidence})
        if not obs.ok or obs.verification.get('verified') is not True:raise RuntimeError('memory_proposal_failed')
        if obs.requires_approval is not True or not obs.approval_id:raise RuntimeError('gen1_memory_review_required')
        candidate.gen1_approval_id=obs.approval_id;candidate.state='REVIEW_PENDING';candidate.review_verification=dict(obs.verification);self.store.save_memory_candidate(candidate);return candidate
    def reconcile(self,candidate_id):
        candidate=self.get(candidate_id)
        if candidate.state in {'PERSISTED','REJECTED','REVIEW_REJECTED','BLOCKED'}:return candidate
        if candidate.state!='REVIEW_PENDING' or not candidate.gen1_approval_id:raise ValueError('memory candidate is not awaiting Gen-1 review')
        state=self.gen1.approval_status(candidate.gen1_approval_id,'memory_write');status=str(state.get('status','UNKNOWN')).upper()
        candidate.review_verification=dict(state)
        if status=='APPROVED' and state.get('verified') is True and state.get('memory_id'):
            candidate.state='PERSISTED';candidate.memory_id=str(state['memory_id'])
            if candidate.supersedes_candidate_id:
                previous=self.get(candidate.supersedes_candidate_id)
                previous.state='SUPERSEDED';self.store.save_memory_candidate(previous)
        elif status=='REJECTED':candidate.state='REVIEW_REJECTED'
        self.store.save_memory_candidate(candidate);return candidate
    def propose_correction(self,candidate_id,value,*,actor='user',owner_user_id='user'):
        previous=self.get(candidate_id)
        if str(actor).strip().lower() in self.FORBIDDEN_APPROVERS or not str(actor).strip():raise PermissionError('human_approval_required')
        if previous.owner_user_id!=owner_user_id:raise PermissionError('memory_owner_mismatch')
        if previous.state!='PERSISTED':raise ValueError('persisted_memory_required')
        if not isinstance(value,str):raise ValueError('bounded_correction_required')
        value=self.analyzer._normalize(value)
        if not 4<=len(value)<=self.analyzer.max_value_chars or self.analyzer._secret(value):raise ValueError('unsafe_memory_correction')
        fingerprint=hashlib.sha256(f'{owner_user_id}|{previous.category}|{value.casefold()}'.encode()).hexdigest()
        identity='memcand_'+hashlib.sha256(f'correction|{candidate_id}|{fingerprint}'.encode()).hexdigest()[:32]
        try:return self.get(identity)
        except KeyError:pass
        candidate=MemoryCandidate(identity,previous.goal_id,previous.task_run_id,previous.trace_id,value,previous.category,
            previous.memory_key,'human proposed correction','human_correction',
            {'supersedes_candidate_id':previous.candidate_id},1.0,previous.privacy_classification,now(),
            owner_user_id=owner_user_id,fingerprint=fingerprint,supersedes_candidate_id=previous.candidate_id)
        self.store.save_memory_candidate(candidate);return candidate
    def recall(self,query,*,owner_user_id='user',limit=5):
        if not isinstance(query,str) or len(query)>1000 or not 1<=limit<=20:raise ValueError('invalid_memory_query')
        terms=set(re.findall(r'[a-z0-9]+',query.lower()))
        candidates=[c for c in self.list() if c.owner_user_id==owner_user_id and c.state=='PERSISTED' and not self.expired(c)]
        candidates.sort(key=lambda c:(-len(terms & set(re.findall(r'[a-z0-9]+',c.value.lower()))),c.candidate_id))
        return [{'candidate_id':c.candidate_id,'value':c.value,'category':c.category,'memory_id':c.memory_id,
                 'source_goal':c.goal_id,'trace_id':c.trace_id,'verified':True} for c in candidates[:limit]
                if not terms or terms & set(re.findall(r'[a-z0-9]+',c.value.lower()))]

    def candidate_for_memory(self,memory_id):
        rows=self.store.memory_candidates(memory_id=str(memory_id));return MemoryCandidate(**rows[0]) if rows else None

class MemoryOrchestrator:
    def __init__(self,gen1):self.gen1=gen1
    def propose(self,category,key,value,*,importance=.5,approved=False):
        if not approved:raise PermissionError('approval_required')
        if 'memory_write' not in set(self.gen1.health().get('tools',[])):raise RuntimeError('memory_write_unavailable')
        obs=self.gen1.invoke('memory_write',{'category':category,'key':key,'value':value,'importance':importance})
        if not obs.ok:raise RuntimeError('memory_proposal_failed')
        return {'output':obs.output,'verification':obs.verification,'requires_gen1_approval':obs.requires_approval,'approval_id':obs.approval_id}
