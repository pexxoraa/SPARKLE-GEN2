from __future__ import annotations
from ...core_time import now

MODES=('MANUAL','APPROVAL_REQUIRED','TRUSTED_ACTIONS','LIMITED_AUTONOMOUS')
class AutonomyController:
    """User-owned unattended-execution ceiling. It can never override deterministic policy."""
    def __init__(self,store):self.store=store
    def get(self):
        value=self.store.load_setting('autonomy',{'mode':'APPROVAL_REQUIRED','updated_at':None})
        if value.get('mode') not in MODES:return {'mode':'APPROVAL_REQUIRED','updated_at':None}
        return value
    def set(self,mode):
        if mode not in MODES:raise ValueError('invalid_autonomy_mode')
        value={'mode':mode,'updated_at':now()};self.store.save_setting('autonomy',value);return value
    def allows_unattended(self,permission_effect,risk_level):
        mode=self.get()['mode']
        if permission_effect!='ALLOW':return False
        if mode in {'MANUAL','APPROVAL_REQUIRED'}:return False
        if mode=='TRUSTED_ACTIONS':return risk_level=='LOW'
        return risk_level in {'LOW','MEDIUM'}
