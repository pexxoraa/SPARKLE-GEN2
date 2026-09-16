from __future__ import annotations

class MemoryOrchestrator:
    def __init__(self,gen1):self.gen1=gen1
    def propose(self,category,key,value,*,importance=.5,approved=False):
        if not approved:raise PermissionError('approval_required')
        if 'memory_write' not in set(self.gen1.health().get('tools',[])):raise RuntimeError('memory_write_unavailable')
        obs=self.gen1.invoke('memory_write',{'category':category,'key':key,'value':value,'importance':importance})
        if not obs.ok:raise RuntimeError('memory_proposal_failed')
        return {'output':obs.output,'verification':obs.verification,'requires_gen1_approval':obs.requires_approval,'approval_id':obs.approval_id}
