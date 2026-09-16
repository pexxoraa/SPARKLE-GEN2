from __future__ import annotations

SAFE_READ_ACTIONS={'inspect','status','screenshot','read'}
DENIED_ACTIONS={'shell','arbitrary_shell','raw_command','sudo'}
class BoundedControlGateway:
    def __init__(self,adapter=None,allowed_actions=None):
        self.adapter=adapter;self.allowed_actions=set(allowed_actions or SAFE_READ_ACTIONS)
    def health(self):return {'status':'CONNECTED' if self.adapter else 'EXTERNALLY_BLOCKED'}
    def invoke(self,action,payload,*,approved=False):
        if action in DENIED_ACTIONS:raise PermissionError('unsafe_action_denied')
        if action not in self.allowed_actions:raise PermissionError('action_not_allowlisted')
        if self.adapter is None:raise RuntimeError('external_dependency:control_environment')
        if action not in SAFE_READ_ACTIONS and not approved:raise PermissionError('approval_required')
        result=self.adapter(action,dict(payload))
        if not isinstance(result,dict):raise RuntimeError('control_invalid_observation')
        return result
