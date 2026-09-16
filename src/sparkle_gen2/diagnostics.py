from __future__ import annotations

class SelfDiagnostics:
    def __init__(self,gen1,store=None,connectors=None): self.gen1=gen1;self.store=store;self.connectors=connectors
    def inspect(self):
        report={'gen1':self.gen1.health(),'storage':{'available':self.store is not None},'connectors':[]}
        if self.connectors is not None:
            report['connectors']=[self.connectors.health(r['name']) for r in self.connectors.discover()]
        report['healthy']=bool(report['gen1'].get('available'))
        return report
