from __future__ import annotations
import uuid
from .models import Permission,PermissionEffect,PermissionStatus,RiskEvaluation,RiskLevel

READ_CAPABILITIES={
    'memory_search',
    'skill_search',
    'knowledge_search',
    'knowledge_verify',
    'project_search',
    'project_tasks',
    'learning_progress',
    'research_workspace',
    'engineering_inspect',
    'content_search',
    'automation_inspect',
    'calculator',
    'ros2_sim_status',
}
WRITE_CAPABILITIES={'ros2_sim_move','memory_write','workspace_scaffold','workspace_verify','workspace_package','workspace_test','agent_install'}

class PolicyEngine:
    def evaluate(self,capability:str,subject:str,scope:str,timestamp:str)->tuple[Permission,RiskEvaluation]:
        if capability in READ_CAPABILITIES:
            effect=PermissionEffect.ALLOW; level=RiskLevel.LOW; auth='GEN1_POLICY'
            rationale='registered bounded read/analysis capability'
        elif capability in WRITE_CAPABILITIES:
            effect=PermissionEffect.REQUIRE_APPROVAL; level=RiskLevel.MEDIUM; auth='USER_APPROVAL_AND_GEN1_POLICY'
            rationale='state-changing capability requires independent approval'
        else:
            effect=PermissionEffect.DENY; level=RiskLevel.HIGH; auth='BLOCKED'
            rationale='capability is not in the Gen-2 policy registry'
        permission=Permission(uuid.uuid4().hex,subject,capability,scope,effect,PermissionStatus.ACTIVE,'gen2-policy',timestamp,metadata={'deterministic':True})
        risk=RiskEvaluation(uuid.uuid4().hex,scope,capability,level,rationale,'gen2-policy',timestamp,auth)
        return permission,risk
