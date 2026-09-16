from __future__ import annotations
import uuid
from datetime import UTC,datetime
from .core_time import now
from .models import Permission,PermissionEffect,PermissionStatus

class PermissionCenter:
    def __init__(self,store,goal_id):self.store=store;self.goal_id=goal_id
    @staticmethod
    def _expired(value):
        if not value:return False
        try:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=UTC)
            return dt<=datetime.now(UTC)
        except (TypeError,ValueError):return True
    def grant(self,subject,capability,scope,effect,*,granted_by='user',expires_at=None,metadata=None):
        if effect not in {PermissionEffect.ALLOW,PermissionEffect.REQUIRE_APPROVAL,PermissionEffect.DENY}:effect=PermissionEffect(str(effect))
        if granted_by=='model':raise PermissionError('model_cannot_grant_permissions')
        p=Permission(uuid.uuid4().hex,subject,capability,scope,effect,PermissionStatus.ACTIVE,granted_by,now(),expires_at,dict(metadata or {}));self.store.save_permission(self.goal_id,p);return p
    def revoke(self,permission_id,*,actor='user'):
        items={p.permission_id:p for p in self.store.permissions_for_goal(self.goal_id)}
        p=items[permission_id]
        if actor=='model':raise PermissionError('model_cannot_revoke_permissions')
        p.status=PermissionStatus.REVOKED;p.metadata=dict(p.metadata)|{'revoked_by':actor,'revoked_at':now()};self.store.save_permission(self.goal_id,p);return p
    def list(self,*,include_inactive=True):
        out=[]
        for p in self.store.permissions_for_goal(self.goal_id):
            if p.status==PermissionStatus.ACTIVE and self._expired(p.expires_at):
                p.status=PermissionStatus.EXPIRED;self.store.save_permission(self.goal_id,p)
            if include_inactive or p.status==PermissionStatus.ACTIVE:out.append(p)
        return out
    def authorize(self,subject,capability,scope):
        matches=[p for p in self.list(include_inactive=False) if p.subject==subject and p.capability==capability and p.scope==scope]
        if not matches:return PermissionEffect.DENY
        effects={p.effect for p in matches}
        if PermissionEffect.DENY in effects:return PermissionEffect.DENY
        if PermissionEffect.REQUIRE_APPROVAL in effects:return PermissionEffect.REQUIRE_APPROVAL
        return PermissionEffect.ALLOW
