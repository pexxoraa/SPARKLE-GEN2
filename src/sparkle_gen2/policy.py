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
    'learning_plan_inspect',
    'research_workspace',
    'engineering_inspect',
    'content_search',
    'automation_inspect',
    'calculator',
    'file_read',
    'data_analyze',
    'document_search',
    'specialist_delegate',
    'ros2_sim_status',
    'perception_observe',
    'daily_brief_generate',
    'daily_brief_inspect',
    'operations_snapshot',
    'notification_inspect',
    'notification_explain',
    'notification_delivery_inspect',
    'notification_channels_inspect',
    'connector_list',
    'connector_inspect',
    'connector_capabilities',
    'connector_health',
    'connector_read',
    'gmail.read',
    'calendar.read',
    'drive.read',
    'github.read',
    'browser.navigate',
    'browser.read',
    'linux.inspect',
    'computer.read',
    'mobile.read',
}
WRITE_CAPABILITIES={'learning_plan_create','learning_assess','mobile.act','computer.act','linux.execute','browser.interact','connector_invoke','connector_write','image_generate','notification_delivery_retry','notification_acknowledge','daily_brief_update','daily_brief_close','document_ingest','ros2_sim_move','memory_write','workspace_scaffold','workspace_verify','workspace_package','workspace_test','agent_install','automation_create','automation_pause','automation_resume','automation_cancel','automation_disable','automation_run_now'}

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
    def evaluate_with_advisory(self,capability:str,subject:str,scope:str,timestamp:str,advisory=None):
        permission,risk=self.evaluate(capability,subject,scope,timestamp)
        if advisory is None:return permission,risk
        result=advisory.get('advisory_result',advisory) if isinstance(advisory,dict) else {}
        flagged=bool(result.get('flagged')) or result.get('label') in {'unsafe','flagged'}
        if not flagged:return permission,risk
        # Advisory output can never grant permission or reduce deterministic risk/approval requirements.
        if permission.effect==PermissionEffect.ALLOW:
            permission.effect=PermissionEffect.REQUIRE_APPROVAL;permission.granted_by='gen2-policy+advisory';permission.metadata=dict(permission.metadata)|{'advisory_escalation':True,'advisory_id':advisory.get('advisory_id') if isinstance(advisory,dict) else None}
            risk.level=RiskLevel.MEDIUM;risk.rationale=risk.rationale+'; advisory safety signal escalated review';risk.evaluated_by='gen2-policy+advisory';risk.required_authorization='USER_APPROVAL_AND_GEN1_POLICY'
        else:
            permission.metadata=dict(permission.metadata)|{'advisory_observed':True,'advisory_id':advisory.get('advisory_id') if isinstance(advisory,dict) else None}
        return permission,risk
