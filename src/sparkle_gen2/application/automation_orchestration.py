from __future__ import annotations
import uuid
from dataclasses import asdict,dataclass,field
from datetime import UTC,datetime
from typing import Any
from ..background import BackgroundTaskService
from ..core_time import now
from ..notifications import NotificationIntelligenceService
from ..model_manager import KNOWN_CAPABILITIES

TRIGGERS=frozenset({'scheduled','event','condition','deadline'})
SCHEDULE_KINDS=frozenset({'once','daily','weekly'})
CONDITION_ALERTS=frozenset({'deadline_approaching','overdue','project_incomplete','repeated_mistake','research_change','revision_due','schedule_conflict','weak_learning'})

@dataclass(slots=True)
class AutomationBinding:
    automation_id:int
    owner_user_id:str
    source_goal_id:str
    trigger_type:str
    required_capabilities:list[str]
    risk:str
    status:str
    created_at:str
    updated_at:str
    last_goal_id:str|None=None
    last_background_id:str|None=None
    last_result:dict[str,Any]=field(default_factory=dict)
    verification_state:str='PENDING'
    def to_dict(self):return asdict(self)

@dataclass(slots=True)
class AutomationObject:
    automation_id:int
    owner_user_id:str
    source_goal_id:str
    trigger_type:str
    schedule:str|None
    condition:dict[str,Any]|None
    action:dict[str,Any]
    required_capabilities:list[str]
    risk:str
    next_run:str|None
    status:str
    created_at:str
    updated_at:str
    last_run:str|None=None
    last_goal_id:str|None=None
    last_background_id:str|None=None
    last_result:dict[str,Any]=field(default_factory=dict)
    verification_state:str='PENDING'
    def to_dict(self):return asdict(self)

class _Gen2AutomationRunner:
    """Adapter around Gen-1 ReliableAutomationRunner; only agent execution is redirected through PersonalAgent."""
    def __init__(self,base_runner,gen2_store,agent_factory,bindings):
        self.base=base_runner;self.store=base_runner.store;self.proactive=base_runner.proactive;self.notifications=base_runner.notifications;self.traces=base_runner.traces;self.gen2_store=gen2_store;self.agent_factory=agent_factory;self.bindings=bindings
    def _execute(self,item):
        action=item['action']
        if action.get('type')!='agent':return self.base._execute(item)
        agent=self.agent_factory();user_id=str(action.get('user_id') or 'user');prompt=str(action['prompt']);required=list(action.get('required_capabilities') or ['planning','reasoning'])
        manager=getattr(getattr(agent,'gen1',None),'model_manager',None)
        if manager is not None:
            route=manager.route(required,input_modalities=['text'],output_modalities=['text'])
            if route.selected is None:raise RuntimeError('automation_model_capability_unavailable:'+','.join(sorted(required)))
        result=agent.start(prompt,user_id=user_id);binding=self.bindings.get(item['id']);goal_id=result['goal_id'];notifier=NotificationIntelligenceService(self.gen2_store)
        background=BackgroundTaskService(self.gen2_store,lambda:agent,notifier=notifier);task=background.create(goal_id,max_iterations=100,time_budget_seconds=float(action.get('time_budget_seconds',300)));task=background.resume(task.background_id)
        if binding is not None:
            binding.last_goal_id=goal_id;binding.last_background_id=task.background_id;binding.last_result={'goal_status':result.get('status'),'background_state':task.state};binding.verification_state='VERIFIED' if task.state=='COMPLETED' else 'FAILED';binding.updated_at=now();self.bindings.save(binding)
        if task.state!='COMPLETED':raise RuntimeError('automation_gen2_goal_not_completed:'+task.state)
        final=agent.resume(goal_id);trace_id=final.get('trace_id');summary=str(final.get('text',''))[:1000]
        return summary,trace_id
    def run_due(self,*args,**kwargs):
        # Reuse the reliable runner's implementation with this object's _execute by
        # temporarily rebinding only the execution hook on the isolated runner instance.
        original=self.base._execute
        try:
            self.base._execute=self._execute
            return self.base.run_due(*args,**kwargs)
        finally:self.base._execute=original

class _BindingStore:
    def __init__(self,store):self.store=store
    def save(self,binding):self.store.save_automation_binding(binding)
    def get(self,automation_id):
        try:return self.store.load_automation_binding(automation_id)
        except KeyError:return None

class AutomationOrchestrator:
    def __init__(self,store,gen1,agent_factory):
        system=getattr(gen1,'system',None)
        if system is None or not hasattr(system,'automations') or not hasattr(system,'automation_runner'):raise RuntimeError('reliable_automation_boundary_unavailable')
        self.store=store;self.gen1=gen1;self.system=system;self.bindings=_BindingStore(store);self.runner=_Gen2AutomationRunner(system.automation_runner,store,agent_factory,self.bindings)
    @staticmethod
    def available(gen1):
        system=getattr(gen1,'system',None);return bool(system is not None and hasattr(system,'automations') and hasattr(system,'automation_runner'))
    def _item(self,automation_id):
        if isinstance(automation_id,bool) or not isinstance(automation_id,int) or automation_id<1:raise ValueError('automation_id is invalid')
        item=next((x for x in self.system.automations.list() if x.get('id')==automation_id),None)
        if item is None:raise KeyError(automation_id)
        return item
    @staticmethod
    def _normalize_condition(trigger_type,condition):
        c=dict(condition or {})
        if trigger_type=='deadline':
            c.setdefault('type','memory_deadline');c.setdefault('alert','deadline_approaching')
        elif trigger_type in {'event','condition'}:c.setdefault('type','proactive_alert')
        if c.get('alert') not in CONDITION_ALERTS:raise ValueError('automation condition alert is unsupported')
        return c
    def create(self,*,owner_user_id,source_goal_id,name,trigger_type,prompt,schedule_kind=None,schedule=None,next_run_at=None,condition=None,required_capabilities=None,risk='MEDIUM',max_attempts=1,time_budget_seconds=300):
        if trigger_type not in TRIGGERS:raise ValueError('automation trigger type is unsupported')
        if not isinstance(owner_user_id,str) or not owner_user_id.strip():raise ValueError('automation owner is required')
        if not isinstance(name,str) or not name.strip() or len(name)>200:raise ValueError('automation name is invalid')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>20000:raise ValueError('automation prompt is invalid')
        caps=list(required_capabilities or ['planning','reasoning'])
        if not caps or any(not isinstance(x,str) or x not in KNOWN_CAPABILITIES for x in caps) or len(set(caps))!=len(caps):raise ValueError('automation required capabilities are invalid')
        if isinstance(max_attempts,bool) or int(max_attempts)!=1:raise ValueError('Gen-2 goal automations use exactly one outer attempt; retry/replan stays inside PersonalAgent')
        if not 0.001<=float(time_budget_seconds)<=86400:raise ValueError('automation time budget is out of range')
        action={'type':'agent','prompt':prompt.strip(),'user_id':owner_user_id,'required_capabilities':caps,'max_attempts':1,'time_budget_seconds':float(time_budget_seconds)}
        if trigger_type=='scheduled':
            kind=str(schedule_kind or 'once')
            if kind not in SCHEDULE_KINDS:raise ValueError('automation schedule kind is unsupported')
            if not next_run_at:raise ValueError('scheduled automation requires next_run_at')
            try:
                parsed=datetime.fromisoformat(str(next_run_at).replace('Z','+00:00'))
                if parsed.tzinfo is None:raise ValueError
            except (TypeError,ValueError):raise ValueError('scheduled automation next_run_at must be an offset-aware ISO timestamp')
            condition_value=None
        else:
            kind='condition';condition_value=self._normalize_condition(trigger_type,condition)
        aid=self.system.automations.create(str(name)[:200],kind,action,schedule=schedule,condition=condition_value,next_run_at=next_run_at)
        stamp=now();binding=AutomationBinding(aid,owner_user_id,source_goal_id,trigger_type,caps,str(risk),'ACTIVE',stamp,stamp);self.bindings.save(binding)
        return self.inspect(aid)
    def inspect(self,automation_id):
        item=self._item(automation_id);binding=self.bindings.get(automation_id);runs=[x for x in self.system.automations.list_runs(limit=100) if x.get('automation_id')==automation_id];attempts=self.system.automations.list_attempts(automation_id,limit=100)
        view=None
        if binding is not None:
            effective=binding.status
            if binding.status=='ACTIVE' and not item.get('enabled') and item.get('last_status')=='success':effective='COMPLETED'
            elif binding.status=='ACTIVE' and item.get('last_status')=='failure':effective='FAILED'
            view=AutomationObject(automation_id,binding.owner_user_id,binding.source_goal_id,binding.trigger_type,item.get('schedule'),item.get('condition'),dict(item.get('action') or {}),list(binding.required_capabilities),binding.risk,item.get('next_run_at'),effective,binding.created_at,binding.updated_at,item.get('last_run_at'),binding.last_goal_id,binding.last_background_id,dict(binding.last_result),binding.verification_state).to_dict()
        return {'automation':item,'binding':None if binding is None else binding.to_dict(),'object':view,'runs':runs,'attempts':attempts}
    def _control(self,automation_id,op,owner_user_id=None):
        item=self._item(automation_id);binding=self.bindings.get(automation_id)
        if binding is None:raise PermissionError('automation is not owned by Gen-2')
        if owner_user_id is not None and binding.owner_user_id!=owner_user_id:raise PermissionError('automation owner mismatch')
        if op=='pause':self.system.automations.set_enabled(automation_id,False);binding.status='PAUSED'
        elif op=='resume':self.system.automations.set_enabled(automation_id,True);binding.status='ACTIVE'
        elif op=='cancel':self.system.automations.set_enabled(automation_id,False);binding.status='CANCELLED'
        elif op=='disable':self.system.automations.set_enabled(automation_id,False);binding.status='DISABLED'
        elif op=='run_now':
            if item['kind']=='condition':raise ValueError('condition automations do not support run-now; trigger evidence is required')
            stamp=now()
            with self.system.automations.connect() as db:db.execute('UPDATE automations SET next_run_at=?,enabled=1,updated_at=? WHERE id=?',(stamp,stamp,automation_id))
            binding.status='ACTIVE'
        else:raise ValueError('automation control is unsupported')
        binding.updated_at=now();self.bindings.save(binding);return self.inspect(automation_id)
    def pause(self,automation_id,owner_user_id=None):return self._control(automation_id,'pause',owner_user_id)
    def resume(self,automation_id,owner_user_id=None):return self._control(automation_id,'resume',owner_user_id)
    def cancel(self,automation_id,owner_user_id=None):return self._control(automation_id,'cancel',owner_user_id)
    def disable(self,automation_id,owner_user_id=None):return self._control(automation_id,'disable',owner_user_id)
    def run_now(self,automation_id,owner_user_id=None):return self._control(automation_id,'run_now',owner_user_id)
    def run_due(self,when=None):
        runs=self.runner.run_due(when)
        for run in runs:
            binding=self.bindings.get(run['automation_id'])
            if binding is None:continue
            binding.last_result=dict(run);binding.verification_state='VERIFIED' if run.get('status')=='success' else 'FAILED';item=self._item(run['automation_id']);binding.status=('ACTIVE' if item.get('enabled') else ('COMPLETED' if run.get('status')=='success' else 'FAILED'));binding.updated_at=now();self.bindings.save(binding)
        return runs
    def invoke(self,tool,args,*,owner_user_id,source_goal_id):
        if tool=='automation_create':
            value=self.create(owner_user_id=owner_user_id,source_goal_id=source_goal_id,**dict(args));method='re-read authoritative Gen-1 automation definition and Gen-2 owner binding'
        elif tool in {'automation_pause','automation_resume','automation_cancel','automation_disable','automation_run_now'}:
            aid=int(args.get('automation_id'));value=getattr(self,tool.removeprefix('automation_'))(aid,owner_user_id);method='re-read authoritative Gen-1 automation control state'
        else:raise ValueError('unsupported automation operation')
        verified=value['binding'] is not None and value['binding']['owner_user_id']==owner_user_id
        if tool=='automation_pause':verified=verified and value['automation']['enabled'] is False and value['binding']['status']=='PAUSED'
        elif tool=='automation_resume':verified=verified and value['automation']['enabled'] is True and value['binding']['status']=='ACTIVE'
        elif tool=='automation_cancel':verified=verified and value['automation']['enabled'] is False and value['binding']['status']=='CANCELLED'
        elif tool=='automation_disable':verified=verified and value['automation']['enabled'] is False and value['binding']['status']=='DISABLED'
        elif tool=='automation_run_now':verified=verified and value['automation']['enabled'] is True and value['automation']['next_run_at'] is not None
        return {'output':value,'verification':{'verified':verified,'method':method,'automation_id':value['automation']['id']}}
