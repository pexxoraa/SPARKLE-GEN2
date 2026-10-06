from __future__ import annotations
import hashlib, json, uuid
from dataclasses import asdict, dataclass, field
from typing import Any
from ..core_time import now

MAX_UNITS=20
MAX_ASSESSMENTS=100
WEAK_THRESHOLD=0.70
MASTERED_THRESHOLD=0.85

@dataclass(slots=True)
class LearningUnit:
    unit_id:str
    title:str
    status:str='PENDING'
    attempts:int=0
    best_score:float|None=None
    updated_at:str|None=None
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class LearningPlanState:
    plan_id:str
    owner_user_id:str
    subject:str
    objective:str
    status:str
    units:list[dict[str,Any]]
    assessments:list[dict[str,Any]]=field(default_factory=list)
    weaknesses:list[str]=field(default_factory=list)
    retraining:list[dict[str,Any]]=field(default_factory=list)
    source_progress:dict[str,Any]=field(default_factory=dict)
    created_at:str=''
    updated_at:str=''
    provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

class LearningOrchestrator:
    """Restart-safe adaptive learning state over verified Gen-1 progress evidence.

    The service never lets model prose establish mastery. Curriculum/assessment mutations are
    expected to pass through PersonalAgent policy/approval. Scores become state only after the
    trusted caller invokes the exact approved operation.
    """
    def __init__(self,store,gen1=None):self.store=store;self.gen1=gen1
    @staticmethod
    def _text(value,name,limit=240):
        if not isinstance(value,str) or not value.strip():raise ValueError(f'{name} is required')
        value=' '.join(value.strip().split())
        if len(value)>limit:raise ValueError(f'{name} exceeds bound')
        low=value.lower()
        if any(x in low for x in ('password=','api_key=','access_token=','refresh_token=','authorization: bearer')):raise ValueError(f'{name} contains secret-like content')
        return value
    @staticmethod
    def _unit_id(plan_id,title,index):return 'lu_'+hashlib.sha256(f'{plan_id}:{index}:{title}'.encode()).hexdigest()[:24]
    @staticmethod
    def _digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def _progress(self,subject):
        if self.gen1 is None:return {'status':'UNAVAILABLE','reason':'gen1_learning_progress_unavailable'}
        obs=self.gen1.invoke('learning_progress',{'course':subject})
        if not getattr(obs,'ok',False) or not isinstance(getattr(obs,'verification',None),dict) or obs.verification.get('verified') is not True:
            return {'status':'UNAVAILABLE','reason':'verified_learning_progress_unavailable'}
        output=dict(obs.output or {})
        # Persist only a digest/shape, never arbitrary learning-engine raw payloads.
        return {'status':'VERIFIED','tool':'learning_progress','verification_method':obs.verification.get('method'),'output_sha256':self._digest(output),'fields':sorted(str(k) for k in output)[:40]}
    def create(self,*,owner_user_id,subject,objective,units):
        owner=self._text(owner_user_id,'owner_user_id',256);subject=self._text(subject,'subject',160);objective=self._text(objective,'objective',500)
        if not isinstance(units,list) or not 1<=len(units)<=MAX_UNITS:raise ValueError('learning units must contain 1..20 items')
        normalized=[];seen=set()
        for raw in units:
            title=self._text(raw,'learning unit',180);key=title.casefold()
            if key in seen:raise ValueError('duplicate learning unit')
            seen.add(key);normalized.append(title)
        identity={'owner':owner,'subject':subject.casefold(),'objective':objective,'units':normalized};plan_id='learn_'+self._digest(identity)[:32]
        try:return self.get(plan_id,owner_user_id=owner)
        except KeyError:pass
        stamp=now();records=[LearningUnit(self._unit_id(plan_id,t,i),t,updated_at=stamp).to_dict() for i,t in enumerate(normalized)]
        source=self._progress(subject);state=LearningPlanState(plan_id,owner,subject,objective,'ACTIVE',records,source_progress=source,created_at=stamp,updated_at=stamp,provenance={'source':'approved_learning_plan','source_progress_status':source['status'],'curriculum_digest':self._digest(normalized)})
        self.store.save_learning_plan(state);return state
    def get(self,plan_id,*,owner_user_id):
        state=self.store.load_learning_plan(str(plan_id))
        if state.owner_user_id!=owner_user_id:raise PermissionError('learning_plan_owner_mismatch')
        return state
    def list(self,*,owner_user_id,limit=20):return self.store.learning_plans(owner_user_id=owner_user_id,limit=limit)
    def assess(self,plan_id,*,owner_user_id,unit_id,score,evidence_reference):
        state=self.get(plan_id,owner_user_id=owner_user_id)
        if state.status not in {'ACTIVE','NEEDS_RETRAINING'}:raise ValueError('learning plan is not assessable')
        if isinstance(score,bool) or not isinstance(score,(int,float)) or not 0<=float(score)<=1:raise ValueError('assessment score must be 0..1')
        evidence=self._text(evidence_reference,'evidence_reference',240)
        unit=next((u for u in state.units if u['unit_id']==unit_id),None)
        if unit is None:raise KeyError(unit_id)
        aid='la_'+self._digest({'plan':plan_id,'unit':unit_id,'score':round(float(score),6),'evidence':evidence})[:32]
        existing=next((a for a in state.assessments if a['assessment_id']==aid),None)
        if existing:return {'plan':state,'assessment':existing,'reused':True}
        if len(state.assessments)>=MAX_ASSESSMENTS:raise RuntimeError('learning assessment limit reached')
        stamp=now();value=float(score);assessment={'assessment_id':aid,'unit_id':unit_id,'score':value,'evidence_reference':evidence,'evidence_sha256':hashlib.sha256(evidence.encode()).hexdigest(),'created_at':stamp}
        state.assessments.append(assessment);unit['attempts']=int(unit.get('attempts',0))+1;unit['best_score']=max(value,float(unit.get('best_score') or 0));unit['updated_at']=stamp
        unit['status']='MASTERED' if unit['best_score']>=MASTERED_THRESHOLD else ('WEAK' if value<WEAK_THRESHOLD else 'PRACTICE')
        weak=[u['unit_id'] for u in state.units if u.get('status')=='WEAK'];state.weaknesses=weak
        for wid in weak:
            attempts=sum(1 for a in state.assessments if a['unit_id']==wid and float(a['score'])<WEAK_THRESHOLD)
            if attempts>=2 and not any(x['unit_id']==wid for x in state.retraining):
                target=next(u for u in state.units if u['unit_id']==wid);state.retraining.append({'unit_id':wid,'title':target['title'],'reason':'repeated_below_threshold_assessment','created_at':stamp})
        if all(u.get('status')=='MASTERED' for u in state.units):state.status='COMPLETED'
        elif state.retraining:state.status='NEEDS_RETRAINING'
        else:state.status='ACTIVE'
        state.updated_at=stamp;state.provenance=dict(state.provenance)|{'last_assessment_id':aid,'assessment_policy':{'weak_below':WEAK_THRESHOLD,'mastered_at_or_above':MASTERED_THRESHOLD}}
        self.store.save_learning_plan(state);return {'plan':state,'assessment':assessment,'reused':False}
    def inspect(self,plan_id,*,owner_user_id):
        state=self.get(plan_id,owner_user_id=owner_user_id)
        return {'plan_id':state.plan_id,'subject':state.subject,'objective':state.objective,'status':state.status,'units':[dict(u) for u in state.units],'weaknesses':list(state.weaknesses),'retraining':[dict(x) for x in state.retraining],'assessment_count':len(state.assessments),'source_progress':dict(state.source_progress),'provenance':dict(state.provenance),'created_at':state.created_at,'updated_at':state.updated_at}
    def invoke(self,tool,args,*,owner_user_id):
        a=dict(args or {})
        if tool=='learning_plan_create':
            value=self.create(owner_user_id=owner_user_id,subject=a.get('subject'),objective=a.get('objective'),units=a.get('units'))
            reread=self.get(value.plan_id,owner_user_id=owner_user_id);verified=reread.provenance.get('curriculum_digest')==value.provenance.get('curriculum_digest')
            return {'output':self.inspect(value.plan_id,owner_user_id=owner_user_id),'verification':{'verified':verified,'method':'persisted owner-scoped learning plan reread','plan_id':value.plan_id}}
        if tool=='learning_assess':
            result=self.assess(str(a.get('plan_id','')),owner_user_id=owner_user_id,unit_id=str(a.get('unit_id','')),score=a.get('score'),evidence_reference=a.get('evidence_reference'))
            state=self.get(result['plan'].plan_id,owner_user_id=owner_user_id);verified=any(x['assessment_id']==result['assessment']['assessment_id'] for x in state.assessments)
            return {'output':{'assessment':dict(result['assessment']),'reused':result['reused'],'plan':self.inspect(state.plan_id,owner_user_id=owner_user_id)},'verification':{'verified':verified,'method':'persisted assessment reread + deterministic mastery policy','assessment_id':result['assessment']['assessment_id']}}
        if tool=='learning_plan_inspect':
            value=self.inspect(str(a.get('plan_id','')),owner_user_id=owner_user_id);return {'output':value,'verification':{'verified':True,'method':'persisted owner-scoped learning plan reread','plan_id':value['plan_id']}}
        raise KeyError(tool)
