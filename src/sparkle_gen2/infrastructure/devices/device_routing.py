from __future__ import annotations

class DeviceRouter:
    """Deterministic policy-side device choice; model proposals cannot override eligibility."""
    def __init__(self,identity_service):self.identities=identity_service
    def eligible(self,capability):
        return [d for d in self.identities.list() if d.get('status')=='ONLINE' and not d.get('revoked_at') and capability in set(d.get('capabilities',[]))]
    def select(self,capability,*,preferred_device_id=None):
        items=self.eligible(capability)
        if preferred_device_id:
            chosen=next((d for d in items if d['device_id']==preferred_device_id),None)
            if chosen:return {'status':'ROUTED','device':chosen,'reason':'user_preference'}
        if not items:return {'status':'UNAVAILABLE','device':None,'reason':'no_online_authorized_device'}
        chosen=sorted(items,key=lambda d:(d.get('kind') not in {'desktop','laptop','workstation'},d.get('name',''),d['device_id']))[0]
        return {'status':'ROUTED','device':chosen,'reason':'deterministic_capability_match'}
