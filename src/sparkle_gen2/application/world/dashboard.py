from __future__ import annotations
import hashlib,html,json,re
from time import monotonic
from dataclasses import asdict,dataclass,field
from datetime import UTC,date,datetime,timedelta
from typing import Any
from ...default_acceptance import build_acceptance_matrix

TERMINAL_GOALS={'COMPLETED','FAILED','CANCELLED'}
ACTIVE_GOALS={'CREATED','UNDERSTANDING','PLANNED','AUTHORIZED','EXECUTING','WAITING','VERIFYING','BLOCKED'}
FAIL_STATES={'FAILED','BLOCKED','WAITING','WAITING_FOR_APPROVAL','DEADLINE_EXPIRED','REPLAN_FAILED'}
SECRET_KEYS={'secret','token','password','credential','api_key','authorization','cookie','private_key','access_token','refresh_token'}

@dataclass(slots=True)
class PersonalOperationsSnapshot:
    owner_user_id:str
    generated_at:str
    day:str
    today:dict[str,Any]
    operations:dict[str,Any]
    intelligence:dict[str,Any]
    next_action:dict[str,Any]
    provenance:dict[str,Any]=field(default_factory=dict)
    def to_dict(self):return asdict(self)

class PersonalOperationsService:
    """Read-only bounded projection over authoritative Gen-2 state."""
    def __init__(self,store,*,daily_os=None,diagnostics=None,model_manager=None,connectors=None,devices=None,world=None,notification_service=None,max_items=20):
        self.store=store
        self.daily_os=daily_os
        self.diagnostics=diagnostics
        self.model_manager=model_manager
        self.connectors=connectors
        self.devices=devices
        self.world=world
        self.notifications=notification_service
        self.max_items=max(5,min(int(max_items),50))
        self._connector_cache={}
        self._connector_cache_at={}
        self._diagnostics_cache=None
        self._diagnostics_cache_at=0.0
        self._health_ttl_seconds=5.0
    @staticmethod
    def _clean_text(value):
        text=str(value)[:1000]
        patterns=[r'(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+',r'(?i)((?:api[_-]?key|token|password|secret|credential)\s*[:=]\s*)[^\s,;]+',r'(?i)\b(?:nvapi|sk|gh[pousr])-[A-Za-z0-9_-]{12,}\b',r'(?i)\bgh[pousr]_[A-Za-z0-9]{12,}\b']
        for pattern in patterns:text=re.sub(pattern,lambda m:(m.group(1)+'[REDACTED]') if m.lastindex else '[REDACTED]',text)
        return text
    @staticmethod
    def _safe(value,depth=0):
        if depth>8:return '[bounded]'
        if isinstance(value,dict):
            out={}
            for k,v in value.items():
                key=str(k);low=key.lower()
                if key!='authorization_state' and any(s in low for s in SECRET_KEYS):continue
                if key in {'requested_scope','rendered','raw','content'}:continue
                out[key]=PersonalOperationsService._safe(v,depth+1)
            return out
        if isinstance(value,list):return [PersonalOperationsService._safe(x,depth+1) for x in value[:50]]
        if isinstance(value,str):return PersonalOperationsService._clean_text(value)
        return value
    @staticmethod
    def _status(v):return getattr(v,'value',v)
    @staticmethod
    def _scope_fingerprint(scope):return hashlib.sha256(str(scope).encode()).hexdigest()[:16]
    def _goals(self,owner):return [g for g in self.store.recent_goals(200) if g.get('user_id','user')==owner]
    @staticmethod
    def _user_visible_work(goal):
        constraints=set(goal.get('constraints') or [])
        if 'task_capture' in constraints:return True
        text=' '.join(str(goal.get('normalized_objective') or goal.get('user_request') or '').lower().strip().split())
        return any(text.startswith(x) for x in ('set a goal','create a goal','add a goal','new goal','my goal is','save as a goal','save this as a goal','make this a goal'))
    def _goal_map(self,owner):return {g['goal_id']:g for g in self._goals(owner)}
    def _task_projection(self,run,goal):
        total=len(run.get('completed_steps',[]))+len(run.get('pending_steps',[]))+len(run.get('failed_steps',[]));progress=100 if run.get('status')=='COMPLETED' else round(100*len(run.get('completed_steps',[]))/max(1,total))
        return {'task_run_id':run.get('task_run_id'),'goal_id':run.get('goal_id'),'goal':self._clean_text(goal.get('user_request',''))[:300],'status':str(goal.get('status') or run.get('status')),'run_status':run.get('status'),'progress':progress,'current_operation':run.get('current_step'),'started_at':run.get('started_at'),'updated_at':run.get('updated_at'),'deadline':run.get('deadline'),'trace_id':run.get('trace_id')}
    def _approval_projection(self,a,goal):
        return {'approval_id':a.approval_id,'goal_id':a.goal_id,'task_run_id':a.task_run_id,'step_id':a.step_id,'goal':self._clean_text(goal.get('user_request',''))[:300],'action':self._clean_text(a.action)[:300],'capability':a.capability,'risk':self._status(a.risk),'status':self._status(a.status),'requested_at':a.requested_at,'expires_at':a.expires_at,'scope_fingerprint':self._scope_fingerprint(a.requested_scope)}
    def _daily(self,owner,day):
        brief=self.store.latest_daily_brief(owner,day=day)
        if brief is None:return {'status':'EMPTY','day':day,'brief':None,'unresolved_count':0,'completed_count':0}
        items=[]
        for x in brief.items[:self.max_items]:
            items.append({'item_id':x.get('item_id'),'source':x.get('source'),'key':x.get('key'),'title':self._clean_text(x.get('title',''))[:300],'summary':self._clean_text(x.get('summary',''))[:500],'score':x.get('score'),'action':x.get('action'),'state':x.get('state'),'carried_forward':bool(x.get('carried_from')),'carried_from':x.get('carried_from'),'provenance':self._safe(x.get('provenance') or {})})
        return {'status':brief.status,'day':brief.day,'brief':{'brief_id':brief.brief_id,'status':brief.status,'updated_at':brief.updated_at,'items':items},'unresolved_count':sum(x['state']=='OPEN' for x in items),'completed_count':sum(x['state']=='DONE' for x in items)}
    def _capabilities(self):
        matrix=build_acceptance_matrix().summary();core=[{'capability':x['capability'],'status':x['status'],'dependency':x.get('dependency'),'limitation':x.get('limitation')} for x in matrix[:120]]
        models=[]
        if self.model_manager is not None:
            for cap in ('reasoning','planning','coding','tool_use','multimodal','voice','embedding','reranking','image_generation','safety','perception'):
                try:
                    s=self.model_manager.status(cap);route=s.get('route') or {};selected=route.get('selected');models.append({'capability':cap,'status':s.get('status'),'provider':None if not selected else selected.get('provider'),'model':None if not selected else selected.get('model_id'),'health':None if not selected else selected.get('health'),'fallback':bool(route.get('fallback',False)),'reason':route.get('selection_reason')})
                except Exception as exc:models.append({'capability':cap,'status':'UNAVAILABLE','reason':type(exc).__name__})
        return {'registry':core,'models':models}
    def _connectors(self,owner):
        if self.connectors is None:return {'status':'UNAVAILABLE','items':[],'counts':{}}
        now_mono=monotonic()
        cached_at=self._connector_cache_at.get(owner,0.0)
        if owner in self._connector_cache and now_mono-cached_at < self._health_ttl_seconds:
            return self._connector_cache[owner]
        items=[];raw_items=[]
        try:discovered=self.connectors.discover(owner_user_id=owner)
        except TypeError:discovered=self.connectors.discover()
        for r in discovered[:self.max_items]:
            cid=r.get('connector_id') or r.get('name')
            try:
                try:h=self.connectors.health(cid,owner_user_id=owner)
                except TypeError:h=self.connectors.health(cid)
                item=dict(r)|{'connector_id':cid,'health_state':h.get('health'),'status':h.get('status'),'authorization_state':h.get('authorization_state',r.get('authorization_state')),'reason':h.get('reason'),'last_checked':h.get('last_checked')}
            except Exception as exc:item=dict(r)|{'connector_id':cid,'status':'UNAVAILABLE','reason':type(exc).__name__}
            raw_items.append(item);items.append(self._safe(item))
        counts={'total':len(raw_items),'configured':sum(bool(x.get('configured')) for x in raw_items),'authorized':sum(bool(x.get('authorized')) for x in raw_items),'healthy':sum(x.get('status')=='HEALTHY' for x in raw_items),'blocked':sum(x.get('status') in {'EXTERNALLY_BLOCKED','BLOCKED','UNAVAILABLE'} for x in raw_items),'authorization_required':sum(x.get('authorization_state') in {'REQUIRED','NOT_CONFIGURED','PENDING','EXPIRED'} for x in raw_items)}
        failures=[{'connector_id':x.get('connector_id'),'status':x.get('status'),'reason':x.get('reason')} for x in items if x.get('status') in {'FAILED','DEGRADED','EXTERNALLY_BLOCKED','UNAVAILABLE'}][:self.max_items]
        result={'status':'AVAILABLE','items':items,'counts':counts,'recent_failures':failures}
        self._connector_cache[owner]=result
        self._connector_cache_at[owner]=monotonic()
        return result
    def _devices(self):
        if self.devices is None:return {'status':'UNAVAILABLE','items':[]}
        items=[]
        for d in self.devices.discover()[:self.max_items]:
            try:h=self.devices.health(d['device_id'])
            except Exception as exc:h={'status':'UNAVAILABLE','reason':type(exc).__name__}
            items.append({'device_id':d['device_id'],'kind':d.get('kind') or d.get('type'),'declared_status':d.get('status'),'health':self._safe(h),'last_seen':d.get('last_seen'),'capabilities':list(d.get('capabilities') or [])[:30]})
        return {'status':'AVAILABLE','items':items}
    def _world(self):
        if self.world is None:return {'status':'UNAVAILABLE','items':[]}
        items=[]
        for n in self.world.snapshot().get('nodes',[])[:self.max_items]:
            age=float(n.get('age_seconds',0));source=(n.get('provenance') or {}).get('source');fresh_limit=10.0 if source=='perception' else 300.0;freshness='FRESH' if age<=fresh_limit else ('STALE' if age<=fresh_limit*12 else 'EXPIRED');items.append({'node_id':n.get('node_id'),'kind':n.get('kind'),'state':self._safe(n.get('state') or {}),'observed_at':n.get('observed_at'),'age_seconds':round(age,3),'freshness':freshness,'provenance':self._safe(n.get('provenance') or {})})
        return {'status':'AVAILABLE','items':items}
    def _notification_delivery(self,owner):
        delivery=getattr(self.notifications,'delivery',None) if self.notifications is not None else None
        if delivery is None:return {'status':'UNAVAILABLE','channels':[],'waiting':[],'failures':[],'unacknowledged_important':[],'last_results':[]}
        try:
            channels=[self._safe(x) for x in delivery.channel_states(owner)];attempts=[self._safe(x) for x in delivery.attempts(owner)];notes={x.get('notification_id'):x for x in self.store.notifications() if x.get('owner_user_id','user')==owner};waiting=[x for x in attempts if x.get('status')=='PENDING'];failures=[x for x in attempts if x.get('status') in {'FAILED','UNAVAILABLE','EXPIRED'}];important=[x for x in attempts if x.get('status')=='ACCEPTED' and x.get('acknowledgement_status')!='ACKNOWLEDGED' and notes.get(x.get('notification_id'),{}).get('priority') in {'HIGH','CRITICAL'}];return {'status':'AVAILABLE','channels':channels[:self.max_items],'waiting':waiting[:self.max_items],'failures':failures[:self.max_items],'unacknowledged_important':important[:self.max_items],'last_results':attempts[-self.max_items:][::-1]}
        except Exception as exc:return {'status':'UNAVAILABLE','channels':[],'waiting':[],'failures':[{'status':'UNAVAILABLE','reason':type(exc).__name__}],'unacknowledged_important':[],'last_results':[]}

    def _diagnostics(self):
        if self.diagnostics is None:return {'status':'UNAVAILABLE','healthy':None,'issues':[]}
        now_mono=monotonic()
        if self._diagnostics_cache is not None and now_mono-self._diagnostics_cache_at < self._health_ttl_seconds:
            return self._diagnostics_cache
        try:
            r=self.diagnostics.inspect()
            result={'status':'AVAILABLE','healthy':bool(r.get('healthy')),'issues':self._safe(r.get('issues',[]))[:self.max_items],'storage':{'available':bool((r.get('storage') or {}).get('available'))}}
            self._diagnostics_cache=result
            self._diagnostics_cache_at=monotonic()
            return result
        except Exception as exc:
            return {'status':'UNAVAILABLE','healthy':False,'issues':[{'component':'diagnostics','cause':type(exc).__name__}]}
    def invalidate_health_cache(self,owner_user_id=None):
        if owner_user_id is None:
            self._connector_cache.clear()
            self._connector_cache_at.clear()
        else:
            self._connector_cache.pop(owner_user_id,None)
            self._connector_cache_at.pop(owner_user_id,None)
        self._diagnostics_cache=None
        self._diagnostics_cache_at=0.0

    def snapshot(self,*,owner_user_id='user',day=None):
        if not isinstance(owner_user_id,str) or not owner_user_id.strip():raise ValueError('operations owner required')
        day=str(day or datetime.now(UTC).date().isoformat());date.fromisoformat(day);goals=self._goals(owner_user_id);gmap={g['goal_id']:g for g in goals};runs=[r for r in self.store.all_task_runs(200) if r.get('goal_id') in gmap];tasks=[self._task_projection(r,gmap[r['goal_id']]) for r in runs];active=[x for x in tasks if x['status'] in ACTIVE_GOALS][:self.max_items];completed=[x for x in tasks if x['status']=='COMPLETED'][:10]
        approvals=[self._approval_projection(a,gmap[a.goal_id]) for a in self.store.all_approvals() if a.goal_id in gmap and self._status(a.status)=='PENDING'][:self.max_items]
        backgrounds=[x.to_dict() for x in self.store.background_tasks() if x.goal_id in gmap][:self.max_items];failures=[]
        for t in tasks:
            if t['status'] in {'FAILED','BLOCKED'} or t['run_status'] in FAIL_STATES:failures.append({'kind':'task','id':t['task_run_id'],'status':t['run_status'] or t['status'],'title':t['goal'],'reason':t['current_operation'] or t['run_status']})
        for b in backgrounds:
            if b.get('state') in {'FAILED','BLOCKED','WAITING','WAITING_FOR_APPROVAL'}:failures.append({'kind':'background','id':b.get('background_id'),'status':b.get('state'),'title':self._clean_text(gmap.get(b.get('goal_id'),{}).get('user_request','Background work'))[:300],'reason':b.get('last_error') or b.get('state')})
        recovery=[]
        owned_goal_ids=set(gmap)
        for e in self.store.recent_events(100):
            if e.get('goal_id') not in owned_goal_ids:continue
            if e.get('event_type') in {'replanned','goal_continuation_requested'}:recovery.append({'kind':'recovery','id':e.get('event_id'),'status':'RECOVERED','title':self._clean_text(gmap.get(e.get('goal_id'),{}).get('user_request','Recovered work'))[:300],'reason':e.get('event_type'),'created_at':e.get('created_at')})
            elif e.get('event_type')=='automatic_replan_failed':recovery.append({'kind':'recovery','id':e.get('event_id'),'status':'FAILED','title':self._clean_text(gmap.get(e.get('goal_id'),{}).get('user_request','Recovery failed'))[:300],'reason':'automatic_replan_failed','created_at':e.get('created_at')})
        now_dt=datetime.now(UTC);soon=now_dt+timedelta(hours=72);deadlines=[]
        for g in goals:
            if not g.get('deadline') or g.get('status') in TERMINAL_GOALS:continue
            try:d=datetime.fromisoformat(str(g['deadline']).replace('Z','+00:00'));d=d if d.tzinfo else d.replace(tzinfo=UTC)
            except ValueError:continue
            if d<=soon:deadlines.append({'goal_id':g['goal_id'],'title':self._clean_text(g.get('user_request',''))[:300],'deadline':g['deadline'],'status':'OVERDUE' if d<now_dt else 'APPROACHING'})
        daily=self._daily(owner_user_id,day);notes=[self._safe(x) for x in (self.notifications.attention(owner_user_id,limit=self.max_items) if self.notifications is not None else self.store.notifications()[-self.max_items:][::-1])]
        caps=self._capabilities();connectors=self._connectors(owner_user_id);devices=self._devices();world=self._world();diagnostics=self._diagnostics();delivery=self._notification_delivery(owner_user_id);failures.extend([{'kind':'diagnostic','id':x.get('id') or x.get('component'),'status':'UNAVAILABLE' if x.get('cause') else 'FAILED','title':x.get('component','diagnostic'),'reason':x.get('cause')} for x in diagnostics.get('issues',[])[:10]])
        next_action={'status':'NONE','title':'No unresolved action','source':'operations'}
        if approvals:next_action={'status':'WAITING_FOR_USER','title':approvals[0]['action'],'source':'approval','reference_id':approvals[0]['approval_id']}
        elif daily.get('brief'):
            open_items=[x for x in daily['brief']['items'] if x['state']=='OPEN']
            if open_items:next_action={'status':'OPEN','title':open_items[0]['title'],'source':'daily_brief','reference_id':open_items[0]['item_id'],'score':open_items[0]['score']}
        elif failures:next_action={'status':failures[0]['status'],'title':failures[0]['title'],'source':failures[0]['kind'],'reference_id':failures[0]['id']}
        active_goals=[{'goal_id':g['goal_id'],'title':self._clean_text(g.get('user_request',''))[:300],'status':g.get('status'),'deadline':g.get('deadline'),'updated_at':g.get('updated_at')} for g in goals if g.get('status') in ACTIVE_GOALS][:self.max_items]
        today={'daily_brief':daily,'active_goals':active_goals,'active_work':active,'approaching_deadlines':deadlines[:self.max_items],'unresolved_work':[x for x in active if x['status'] in {'WAITING','BLOCKED'}][:self.max_items],'notifications':notes,'attention':failures[:self.max_items]}
        operations={'background_tasks':backgrounds,'pending_approvals':approvals,'recent_completed':completed,'failed_or_recovered':(failures+recovery)[:self.max_items],'notification_delivery':delivery}
        intelligence={'capabilities':caps,'connectors':connectors,'devices':devices,'world_state':world,'diagnostics':diagnostics,'notification_channels':{'status':delivery.get('status'),'items':delivery.get('channels',[])}}
        return PersonalOperationsSnapshot(owner_user_id,datetime.now(UTC).isoformat(),day,today,operations,intelligence,next_action,{'sources':['daily_briefs','goals','task_runs','approvals','background_tasks','notifications','notification_delivery_attempts','notification_channel_states','capability_registry','model_manager','connectors','devices','world_model','diagnostics'],'bounded':True}).to_dict()
    def invoke(self,args,*,user_id):
        value=self.snapshot(owner_user_id=user_id,day=args.get('day'))
        return {'output':value,'verification':{'verified':value.get('owner_user_id')==user_id and value.get('provenance',{}).get('bounded') is True,'method':'re-read bounded authoritative Personal Operations projection','day':value.get('day')}}

class ReadOnlyDashboard:
    def snapshot(self,*,capabilities=None,tasks=None,connectors=None,diagnostics=None):return {'capabilities':capabilities or [],'tasks':tasks or [],'connectors':connectors or [],'diagnostics':diagnostics or {}}
    def render_html(self,snapshot):
        data=html.escape(json.dumps(snapshot,sort_keys=True,ensure_ascii=False));return '<!doctype html><html><head><meta charset="utf-8"><title>SPARKLE</title></head><body><h1>SPARKLE</h1><pre>'+data+'</pre></body></html>'
