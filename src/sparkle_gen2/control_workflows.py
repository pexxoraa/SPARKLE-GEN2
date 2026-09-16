from __future__ import annotations

class ObserveActVerifyWorkflow:
    """Goal-oriented digital control wrapper. It never bypasses BoundedControlGateway allowlists/approvals."""
    def __init__(self,gateway,*,observe_action='inspect'):self.gateway=gateway;self.observe_action=observe_action
    def execute(self,action,payload,*,approved=False):
        before=self.gateway.invoke(self.observe_action,{'phase':'before'},approved=False)
        result=self.gateway.invoke(action,payload,approved=approved)
        after=self.gateway.invoke(self.observe_action,{'phase':'after'},approved=False)
        verifier=getattr(self.gateway.adapter,'verify',None)
        evidence=verifier(action,result,before,after) if verifier else {'verified':False,'reason':'adapter_has_no_verifier'}
        if not isinstance(evidence,dict) or evidence.get('verified') is not True:raise RuntimeError('control_verification_failed')
        return {'before':before,'result':result,'after':after,'verification':evidence}
