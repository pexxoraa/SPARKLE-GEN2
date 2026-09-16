from __future__ import annotations

class ModelCapabilityManager:
    def __init__(self,gen1):self.gen1=gen1
    def inventory(self):return list(self.gen1.health().get('models',[]))
    def eligible(self,capability):
        out=[]
        for m in self.inventory():
            if m.get('enabled') and capability in set(m.get('roles',[])) and m.get('health')!='UNAVAILABLE':out.append(m)
        return out
    def status(self,capability):
        candidates=self.eligible(capability)
        return {'capability':capability,'status':'CONNECTED' if candidates else 'EXTERNALLY_BLOCKED','candidates':candidates}
