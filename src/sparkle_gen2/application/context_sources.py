from __future__ import annotations

import re
from ..context_engine import ContextItem,PersonalContextEngine

class PersonalContextAssembler:
    """Build bounded context from available personal/data/control sources without requiring all sources to exist."""
    def __init__(self,engine=None,*,personal_data=None,connectors=None,store=None,devices=None,world=None,semantic_index=None):
        self.engine=engine or PersonalContextEngine();self.personal_data=personal_data;self.connectors=connectors;self.store=store;self.devices=devices;self.world=world;self.semantic_index=semantic_index
    def _item(self,source,key,value,provenance=None,freshness=1.0,relevance=1.0):
        return ContextItem(source,key,str(value),freshness,relevance,'ALLOW',dict(provenance or {}))

    @staticmethod
    def _goal_text(goal):
        return ' '.join(str(goal).lower().split())

    @classmethod
    def _needs_email(cls,goal):
        text=cls._goal_text(goal)
        return any(token in text for token in (
            'email','emails','mail','mailbox','inbox','outlook',
            'gmail','message','messages'
        ))

    @classmethod
    def _needs_files(cls,goal):
        text=cls._goal_text(goal)
        return any(token in text for token in (
            'file','files','document','documents','pdf','spreadsheet',
            'csv','attachment','folder','directory','workspace',
            'source code','codebase','script','python file'
        ))

    @classmethod
    def _needs_semantic(cls,goal):
        text=cls._goal_text(goal)
        words=set(re.findall(r'[a-z0-9_]+',text))
        if words & {
            'my','mine','our','memory','remember','preference','preferences',
            'project','projects','task','tasks','research','learning','course',
            'goal','goals','decision','decisions','document','documents',
            'file','files','email','emails','calendar','meeting','meetings',
            'schedule','github','repository','repo','robot','robotics',
            'device','devices','today','tomorrow','recent','latest'
        }:
            return True

        return any(
            re.search(rf'\b{re.escape(phrase)}\b', text)
            for phrase in (
                'what i',
                'what do i',
                'who am i',
                'my history',
                'my preferences',
                'my memory',
                'source code',
                'codebase',
            )
        )
    @classmethod
    def _needs_personal_data(cls,goal):
        text=cls._goal_text(goal)
        return any(token in text.split() for token in (
            'my','mine','our','personal','remember','memory',
            'preference','preferences','project','projects',
            'task','tasks','research','learning','course',
            'goal','goals','decision','decisions','profile',
            'history','previous','past'
        ))

    def gather(self,goal,*,owner_user_id='user',optimized=False):
        sources={}
        if self.personal_data is not None and (not optimized or self._needs_personal_data(goal)):
            for source in ('memory','knowledge','projects','tasks','learning','research'):
                try:r=self.personal_data.retrieve(source,goal,limit=5);sources.setdefault(source,[]).append(self._item(source,source,r.get('output'),{'tool':r.get('tool'),'verification':r.get('verification')}))
                except Exception:pass
            try:
                r=self.personal_data.retrieve('memory',goal,limit=5);sources.setdefault('preferences',[]).append(self._item('preferences','preferences',r.get('output'),{'tool':r.get('tool'),'semantic':'preferences'}))
            except Exception:pass
        if self.connectors is not None:
            if not optimized:
                for name,scope in (('outlook','outlook.read'),('files','files.read')):
                    try:
                        h=self.connectors.health(name,owner_user_id=owner_user_id)
                        if h.get('status') not in {'CONNECTED','HEALTHY'}:continue
                        op='search' if name in {'outlook','files'} else 'list';r=self.connectors.invoke(name,op,{'query':goal},scope,owner_user_id=owner_user_id);item=self._item(name,name,r.get('result'),{'connector':name});sources.setdefault(name,[]).append(item)
                        if name=='outlook':sources.setdefault('email',[]).append(self._item('email',name,r.get('result'),{'connector':'outlook'}))
                    except Exception:pass
            else:
                if self._needs_email(goal):
                    try:
                        h=self.connectors.health('outlook',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke('outlook','search',{'query':goal},'outlook.read',owner_user_id=owner_user_id);item=self._item('outlook','outlook',r.get('result'),{'connector':'outlook'});sources.setdefault('outlook',[]).append(item);sources.setdefault('email',[]).append(self._item('email','outlook',r.get('result'),{'connector':'outlook'}))
                    except Exception:pass

                if self._needs_files(goal):
                    try:
                        h=self.connectors.health('files',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke('files','search',{'query':goal},'files.read',owner_user_id=owner_user_id);item=self._item('files','files',r.get('result'),{'connector':'files'});sources.setdefault('files',[]).append(item)
                    except Exception:pass
            try:
                calendar_ops={x.get('operation') for x in self.connectors.capabilities('calendar')}
            except Exception:calendar_ops=set()
            if 'list_events' in calendar_ops:
                goal_text=str(goal).lower()
                if any(token in goal_text for token in ('calendar','meeting','schedule','event','appointment','today','tomorrow','upcoming')):
                    try:
                        h=self.connectors.health('calendar',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke_read('calendar','list_events',{'calendar_id':'primary','max_results':5},'calendar.read',owner_user_id=owner_user_id,classification='PRIVATE');value=r.get('result');prov={'connector':'calendar','request_id':r.get('request_id'),'verified':bool((r.get('verification') or {}).get('verified'))};sources.setdefault('calendar',[]).append(self._item('calendar','upcoming_events',value,prov))
                    except Exception:pass
            else:
                try:
                    h=self.connectors.health('calendar',owner_user_id=owner_user_id)
                    if h.get('status') in {'CONNECTED','HEALTHY'}:
                        r=self.connectors.invoke('calendar','read',{'query':goal},'calendar.read',owner_user_id=owner_user_id);sources.setdefault('calendar',[]).append(self._item('calendar','calendar',r.get('result'),{'connector':'calendar','legacy':True}))
                except Exception:pass
            try:
                drive_ops={x.get('operation') for x in self.connectors.capabilities('drive')}
            except Exception:drive_ops=set()
            if 'list_files' in drive_ops:
                goal_text=str(goal).lower()
                if any(token in goal_text for token in ('drive','file','document','spreadsheet','pdf','python','modified','recent')):
                    try:
                        h=self.connectors.health('drive',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke_read('drive','list_files',{'max_results':5},'drive.read',owner_user_id=owner_user_id,classification='PRIVATE');value=r.get('result');prov={'connector':'drive','request_id':r.get('request_id'),'verified':bool((r.get('verification') or {}).get('verified'))};sources.setdefault('drive',[]).append(self._item('drive','recent_files',value,prov))
                    except Exception:pass
            try:
                github_ops={x.get('operation') for x in self.connectors.capabilities('github')}
            except Exception:github_ops=set()
            if 'list_repositories' in github_ops:
                goal_text=str(goal).lower()
                if any(token in goal_text for token in ('github','repository',' repo ','repo ','issue','pull request',' pr ','workflow','code repository')):
                    try:
                        h=self.connectors.health('github',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke_read('github','list_repositories',{'max_results':5},'github.read',owner_user_id=owner_user_id,classification='PRIVATE');value=r.get('result');prov={'connector':'github','request_id':r.get('request_id'),'verified':bool((r.get('verification') or {}).get('verified'))};sources.setdefault('github',[]).append(self._item('github','repositories',value,prov))
                    except Exception:pass
            try:
                gmail_ops={x.get('operation') for x in self.connectors.capabilities('gmail')}
            except Exception:gmail_ops=set()
            if 'list_messages' in gmail_ops:
                goal_text=str(goal).lower()
                if any(token in goal_text for token in ('gmail','email','mailbox','recent mail','new mail')):
                    try:
                        h=self.connectors.health('gmail',owner_user_id=owner_user_id)
                        if h.get('status') in {'CONNECTED','HEALTHY'}:
                            r=self.connectors.invoke_read('gmail','list_messages',{'max_results':5},'gmail.read',owner_user_id=owner_user_id,classification='PRIVATE');value=r.get('result');prov={'connector':'gmail','request_id':r.get('request_id'),'verified':bool((r.get('verification') or {}).get('verified'))};sources.setdefault('gmail',[]).append(self._item('gmail','recent_messages',value,prov));sources.setdefault('email',[]).append(self._item('email','gmail',value,prov))
                    except Exception:pass
            else:
                try:
                    h=self.connectors.health('gmail',owner_user_id=owner_user_id)
                    if h.get('status') in {'CONNECTED','HEALTHY'}:
                        r=self.connectors.invoke('gmail','search',{'query':goal},'gmail.read',owner_user_id=owner_user_id);item=self._item('gmail','gmail',r.get('result'),{'connector':'gmail'});sources.setdefault('gmail',[]).append(item);sources.setdefault('email',[]).append(self._item('email','gmail',r.get('result'),{'connector':'gmail'}))
                except Exception:pass
        if self.store is not None:
            try:sources['goals']=[self._item('goals',g.get('goal_id','goal'),g,{'store':'gen2'}) for g in self.store.recent_goals(8)]
            except Exception:pass
            try:sources['recent_activity']=[self._item('recent_activity',e.get('event_type','event'),e,{'store':'gen2'}) for e in self.store.recent_events(12)]
            except Exception:pass
        if self.devices is not None:
            items=[]
            for d in self.devices.discover():
                try:detail=self.devices.health(d['device_id'])
                except Exception:detail={'status':'UNAVAILABLE','verified':False}
                items.append(self._item('devices',d['device_id'],{'record':d,'health':detail},{'device_id':d['device_id']}))
            if items:sources['devices']=items
        if self.semantic_index is not None and (not optimized or self._needs_semantic(goal)):
            try:sources['semantic']=self.semantic_index.context_items(goal,k=5)
            except Exception:pass
        if self.world is not None:
            try:
                items=[]
                for n in self.world.snapshot().get('nodes',[]):
                    age=float(n.get('age_seconds',0));prov=n.get('provenance',{}) or {};limit=10.0 if prov.get('source')=='perception' else 30.0
                    if age>limit:continue
                    items.append(self._item('world_state',n['node_id'],n,prov,freshness=max(0.0,1.0-min(age/max(limit,1e-9),1.0))))
                if items:sources['world_state']=items
            except Exception:pass
        return self.engine.build(goal,sources)
