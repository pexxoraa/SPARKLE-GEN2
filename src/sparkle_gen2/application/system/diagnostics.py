from __future__ import annotations

class SelfDiagnostics:
    def __init__(self,gen1,store=None,connectors=None,devices=None):
        self.gen1=gen1;self.store=store;self.connectors=connectors;self.devices=devices
    def _storage(self):
        if self.store is None:return {'available':False,'reason':'not_configured'}
        if not hasattr(self.store,'connect'):return {'available':False,'reason':'not_inspectable'}
        try:
            with self.store.connect() as db:db.execute('SELECT 1').fetchone()
            return {'available':True,'path':str(getattr(self.store,'path',''))}
        except Exception as exc:return {'available':False,'reason':type(exc).__name__}
    def inspect(self):
        gen1=self.gen1.health();models=list(gen1.get('models',[]));tools=list(gen1.get('tools',[]))
        report={'gen1':gen1,'models':models,'providers':sorted({m.get('provider') for m in models if m.get('provider')}),'tools':tools,'agents':list(gen1.get('agents',[])),'storage':self._storage(),'connectors':[],'devices':[],'background_tasks':[],'issues':[]}
        if self.connectors is not None:
            report['connectors']=[self.connectors.health(r['name']) for r in self.connectors.discover()]
        if self.devices is not None:
            report['devices']=[{'device_id':r['device_id']}|self.devices.health(r['device_id']) for r in self.devices.discover()]
        if self.store is not None:
            try:report['background_tasks']=[t.to_dict() for t in self.store.background_tasks()]
            except Exception as exc:report['issues'].append({'component':'background_tasks','cause':type(exc).__name__})
        for model in models:
            if model.get('enabled') and model.get('health') not in {'AVAILABLE','HEALTHY'}:
                report['issues'].append({'component':'model','id':model.get('record_id'),'provider':model.get('provider'),'cause':model.get('health')})
        for connector in report['connectors']:
            if connector.get('status')=='EXTERNALLY_BLOCKED':report['issues'].append({'component':'connector','id':connector.get('name'),'cause':connector.get('dependency')})
        for device in report['devices']:
            if device.get('status')=='EXTERNALLY_BLOCKED':report['issues'].append({'component':'device','id':device.get('device_id'),'cause':device.get('dependency')})
        for task in report['background_tasks']:
            if task.get('state') in {'BLOCKED','FAILED'}:report['issues'].append({'component':'background_task','id':task.get('background_id'),'cause':task.get('last_error') or task.get('state')})
        storage_required=self.store is not None and hasattr(self.store,'connect')
        report['healthy']=bool(gen1.get('available')) and (not storage_required or report['storage'].get('available',False))
        return report
    def diagnose(self,component=None):
        report=self.inspect();issues=report['issues']
        if component is not None:issues=[i for i in issues if i.get('component')==component or i.get('id')==component]
        return {'healthy':report['healthy'],'issues':issues,'evidence':report}
