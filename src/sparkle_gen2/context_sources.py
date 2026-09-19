from __future__ import annotations
from .context_engine import ContextItem,PersonalContextEngine

class PersonalContextAssembler:
    """Build bounded context from available personal/data/control sources without requiring all sources to exist."""
    def __init__(self,engine=None,*,personal_data=None,connectors=None,store=None,devices=None,world=None,semantic_index=None):
        self.engine=engine or PersonalContextEngine();self.personal_data=personal_data;self.connectors=connectors;self.store=store;self.devices=devices;self.world=world;self.semantic_index=semantic_index
    def _item(self,source,key,value,provenance=None,freshness=1.0,relevance=1.0):
        return ContextItem(source,key,str(value),freshness,relevance,'ALLOW',dict(provenance or {}))
    def gather(self,goal):
        sources={}
        if self.personal_data is not None:
            for source in ('memory','knowledge','projects','tasks','learning','research'):
                try:r=self.personal_data.retrieve(source,goal,limit=5);sources.setdefault(source,[]).append(self._item(source,source,r.get('output'),{'tool':r.get('tool'),'verification':r.get('verification')}))
                except Exception:pass
            try:
                r=self.personal_data.retrieve('memory',goal,limit=5);sources.setdefault('preferences',[]).append(self._item('preferences','preferences',r.get('output'),{'tool':r.get('tool'),'semantic':'preferences'}))
            except Exception:pass
        if self.connectors is not None:
            for name,scope in (('calendar','calendar.read'),('gmail','gmail.read'),('outlook','outlook.read'),('files','files.read')):
                try:
                    h=self.connectors.health(name)
                    if h.get('status') not in {'CONNECTED','HEALTHY'}:continue
                    op='search' if name in {'gmail','outlook','files'} else 'list'
                    r=self.connectors.invoke(name,op,{'query':goal},scope);item=self._item(name,name,r.get('result'),{'connector':name});sources.setdefault(name,[]).append(item)
                    if name in {'gmail','outlook'}:sources.setdefault('email',[]).append(self._item('email',name,r.get('result'),{'connector':name}))
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
        if self.semantic_index is not None:
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
