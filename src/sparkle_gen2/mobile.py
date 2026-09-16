from __future__ import annotations

class MobilePlatformAdapter:
    """Lifecycle orchestration around a bounded mobile target adapter."""
    def __init__(self,target=None):self.target=target
    def health(self):return {'status':'CONNECTED' if self.target else 'EXTERNALLY_BLOCKED','dependency':None if self.target else 'mobile target/emulator'}
    def _call(self,name,*args,**kwargs):
        if self.target is None:raise RuntimeError('external_dependency:mobile_target')
        fn=getattr(self.target,name,None)
        if fn is None:raise RuntimeError('mobile_operation_unsupported:'+name)
        result=fn(*args,**kwargs)
        if not isinstance(result,dict):raise RuntimeError('mobile_invalid_observation')
        return result
    def lifecycle(self,app,credentials_ref,operation,payload,*,approved=False):
        if not approved:raise PermissionError('approval_required')
        evidence={}
        for name,args in (('install',(app,)),('authenticate',(credentials_ref,)),('execute',(operation,dict(payload))),('persist',()),('reopen',(app,)),('sync',()),('notify',())):
            evidence[name]=self._call(name,*args)
        verify=getattr(self.target,'verify',None)
        if verify is None:raise RuntimeError('mobile_verification_unavailable')
        v=verify(operation,evidence)
        if not isinstance(v,dict) or v.get('verified') is not True:raise RuntimeError('mobile_verification_failed')
        evidence['verification']=v;return evidence
    def logout(self):return self._call('logout')
