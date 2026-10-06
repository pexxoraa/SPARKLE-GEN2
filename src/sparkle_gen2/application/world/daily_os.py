from __future__ import annotations
import ast,hashlib,json
from dataclasses import asdict,dataclass,field
from datetime import UTC,date,datetime
from typing import Any
from ...core_time import now

DAILY_OS_VERSION='daily-os-v2'
ITEM_STATES=frozenset({'OPEN','DONE','DISMISSED'})
BRIEF_STATES=frozenset({'READY','CLOSED'})

@dataclass(slots=True)
class DailyBriefItem:
    item_id:str;source:str;key:str;title:str;summary:str;score:float;action:str|None;state:str;provenance:dict[str,Any];carried_from:str|None=None
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class DailyBrief:
    brief_id:str;owner_user_id:str;day:str;context_digest:str;status:str;items:list[dict[str,Any]];created_at:str;updated_at:str;processing_version:str=DAILY_OS_VERSION;source_count:int=0;carry_count:int=0
    def to_dict(self):return asdict(self)

class DailyOperatingSystem:
    USER_RELEVANT_ACTIVITY=frozenset({'deadline_approaching','overdue','project_incomplete','repeated_mistake','research_change','revision_due','schedule_conflict','weak_learning','automation_failure','device_failure','research_finished','important_email','meeting_approaching'})
    SOURCE_IMPORTANCE={'goals':1.0,'tasks':1.0,'calendar':.95,'email':.8,'projects':.85,'recent_activity':.65,'devices':.7,'world_state':.65,'research':.6,'learning':.55,'memory':.5,'preferences':.5}
    def build_brief(self,items):
        normalized=[]
        for item in items:
            urgency=float(item.get('urgency',0));importance=float(item.get('importance',0));relevance=float(item.get('relevance',1))
            score=urgency*0.45+importance*0.4+relevance*0.15
            normalized.append((score,item))
        normalized.sort(key=lambda x:(-x[0],str(x[1].get('title',''))))
        return [{'title':i.get('title','Untitled'),'kind':i.get('kind','item'),'score':round(s,3),'action':i.get('action')} for s,i in normalized]
    def from_context(self,context,*,max_items=10):
        return [{'title':x.title,'kind':x.source,'score':x.score,'action':x.action} for x in self.structured_items(context,max_items=max_items)]
    def structured_items(self,context,*,max_items=10):
        if not 1<=int(max_items)<=50:raise ValueError('max_items out of range')
        ranked=[]
        for entry in context.get('items',[]):
            source=str(entry.get('source','item'));key=str(entry.get('key') or source);value=str(entry.get('value',''))[:1200]
            if source=='recent_activity' and key not in self.USER_RELEVANT_ACTIVITY:continue
            title=key
            if source=='goals':
                try:
                    parsed=ast.literal_eval(value)
                    if isinstance(parsed,dict):
                        if str(parsed.get('status','')).upper() in {'COMPLETED','CANCELLED','FAILED'}:continue
                        title=str(parsed.get('user_request') or 'Active goal')[:160]
                except (ValueError,SyntaxError):title='Active goal'
            relevance=min(1.0,max(0.0,float(entry.get('score',.5))));importance=self.SOURCE_IMPORTANCE.get(source,.5);low=value.lower();urgency=.9 if any(x in low for x in ('deadline','today','overdue','failure','fault')) else .3;score=round(urgency*.45+importance*.4+relevance*.15,3);action='review' if source in {'email','recent_activity','research'} else 'continue';semantic=hashlib.sha256(json.dumps({'source':source,'key':key,'value':value},sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20];ranked.append((score,semantic,source,key,title,value,action,dict(entry.get('provenance') or {})))
        ranked.sort(key=lambda x:(-x[0],x[3],x[1]));out=[]
        for score,semantic,source,key,title,value,action,prov in ranked[:int(max_items)]:
            out.append(DailyBriefItem(semantic,source,key,title,value[:500],score,action,'OPEN',prov))
        return out

class DailyOperatingSystemService:
    def __init__(self,store,context_provider,*,max_items=10):self.store=store;self.context_provider=context_provider;self.max_items=int(max_items);self.rank=DailyOperatingSystem()
    @staticmethod
    def _day(value=None):
        if value is None:return datetime.now(UTC).date().isoformat()
        try:return date.fromisoformat(str(value)).isoformat()
        except ValueError:raise ValueError('daily brief day must be YYYY-MM-DD')
    @staticmethod
    def _digest(context):
        bounded=[{'source':x.get('source'),'key':x.get('key'),'value':str(x.get('value',''))[:1200],'score':x.get('score'),'provenance':x.get('provenance',{})} for x in context.get('items',[])[:50]]
        return hashlib.sha256(json.dumps(bounded,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def available(self):return self.context_provider is not None and callable(getattr(self.context_provider,'gather',None))
    def generate(self,*,user_id,day=None,focus='daily priorities deadlines tasks projects calendar email research learning',max_items=None):
        if not self.available():raise RuntimeError('daily_context_unavailable')
        if not isinstance(user_id,str) or not user_id.strip():raise ValueError('daily brief owner is required')
        day=self._day(day);limit=self.max_items if max_items is None else int(max_items);context=self.context_provider.gather(str(focus)[:500]);digest=self._digest(context);brief_id='daily_'+hashlib.sha256(f'{user_id}\0{day}\0{digest}\0{DAILY_OS_VERSION}'.encode()).hexdigest()[:32]
        try:return self.store.load_daily_brief(brief_id)
        except KeyError:pass
        items=self.rank.structured_items(context,max_items=limit);current_ids={x.item_id for x in items};carry=[]
        prev=self.store.latest_daily_brief(user_id,before_day=day)
        if prev is not None:
            for raw in prev.items:
                if raw.get('state')!='OPEN':continue
                semantic=raw['item_id']
                if semantic in current_ids:continue
                carry.append(DailyBriefItem(semantic,raw['source'],raw['key'],raw['title'],raw.get('summary','')[:500],float(raw['score']),raw.get('action'),'OPEN',dict(raw.get('provenance') or {})|{'carried_from_brief':prev.brief_id},prev.brief_id))
        combined=(items+carry);combined.sort(key=lambda x:(-x.score,x.title,x.item_id));combined=combined[:limit];stamp=now();brief=DailyBrief(brief_id,user_id,day,digest,'READY',[x.to_dict() for x in combined],stamp,stamp,DAILY_OS_VERSION,len(context.get('items',[])),sum(1 for x in combined if x.carried_from));self.store.save_daily_brief(brief);return brief
    def inspect(self,*,user_id,brief_id=None,day=None):
        if brief_id is not None:b=self.store.load_daily_brief(str(brief_id))
        else:b=self.store.latest_daily_brief(user_id,day=self._day(day))
        if b is None:raise KeyError('daily brief not found')
        if b.owner_user_id!=user_id:raise PermissionError('daily brief owner mismatch')
        return b
    def update_item(self,*,user_id,brief_id,item_id,state):
        if state not in {'DONE','DISMISSED'}:raise ValueError('daily item state must be DONE or DISMISSED')
        b=self.inspect(user_id=user_id,brief_id=brief_id);found=False
        for item in b.items:
            if item['item_id']==item_id:item['state']=state;found=True;break
        if not found:raise KeyError(item_id)
        b.updated_at=now();self.store.save_daily_brief(b);return self.inspect(user_id=user_id,brief_id=brief_id)
    def close(self,*,user_id,brief_id):
        b=self.inspect(user_id=user_id,brief_id=brief_id);b.status='CLOSED';b.updated_at=now();self.store.save_daily_brief(b);return self.inspect(user_id=user_id,brief_id=brief_id)
    def invoke(self,tool,args,*,user_id):
        if tool=='daily_brief_generate':b=self.generate(user_id=user_id,day=args.get('day'),focus=args.get('focus','daily priorities deadlines tasks projects calendar email research learning'),max_items=args.get('max_items'));method='re-read persisted daily brief and context digest'
        elif tool=='daily_brief_inspect':b=self.inspect(user_id=user_id,brief_id=args.get('brief_id'),day=args.get('day'));method='re-read persisted daily brief'
        elif tool=='daily_brief_update':b=self.update_item(user_id=user_id,brief_id=str(args.get('brief_id','')),item_id=str(args.get('item_id','')),state=str(args.get('state','')));method='re-read exact daily item disposition'
        elif tool=='daily_brief_close':b=self.close(user_id=user_id,brief_id=str(args.get('brief_id','')));method='re-read closed daily brief state'
        else:raise ValueError('unsupported daily OS operation')
        reread=self.store.load_daily_brief(b.brief_id);verified=reread.owner_user_id==user_id and reread.brief_id==b.brief_id and reread.context_digest==b.context_digest
        return {'output':reread.to_dict(),'verification':{'verified':verified,'method':method,'brief_id':b.brief_id,'day':b.day}}
