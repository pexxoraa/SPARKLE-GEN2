"""Adapter dispatch stays separate from persistent execution policy and lifecycle."""
from __future__ import annotations
import json
from ...gen1 import ToolObservation
from ...domain.models import PermissionEffect
from ...core_time import now


class ExecutionToolDispatcher:
    def invoke(self, agent, goal, plan, run, step, *, request):
        if request.tool_id!=step.preferred_tool or request.owner_user_id!=goal.user_id or request.goal_id!=goal.goal_id or request.task_run_id!=run.task_run_id or request.step_id!=step.step_id or request.arguments!=step.arguments:
            raise PermissionError('tool_input_correlation_mismatch')
        goal_id=goal.goal_id;trace_id=run.trace_id
        if step.preferred_tool in {'learning_plan_create','learning_plan_inspect','learning_assess'} and agent.learning is not None:
            value=agent.learning.invoke(step.preferred_tool,step.arguments,owner_user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            agent.store.event(goal_id,'learning_state_updated' if step.preferred_tool!='learning_plan_inspect' else 'learning_state_inspected',{'tool':step.preferred_tool,'plan_id':value['verification'].get('plan_id'),'assessment_id':value['verification'].get('assessment_id')},now())
        elif step.preferred_tool.startswith('automation_') and agent.automation is not None and step.preferred_tool!='automation_inspect':
            value=agent.automation.invoke(step.preferred_tool,step.arguments,owner_user_id=goal.user_id,source_goal_id=goal.goal_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
        elif step.preferred_tool=='connector_list' and agent.connectors is not None:
            value={'connectors':agent.connectors.discover(owner_user_id=goal.user_id)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':all(x.get('connector_id') for x in value['connectors']),'method':'owner-scoped persisted connector registry projection'})
        elif step.preferred_tool=='connector_inspect' and agent.connectors is not None:
            cid=str(step.arguments.get('connector_id',''))
            if not cid:
                obs=ToolObservation(False,step.preferred_tool,{'error':'missing_required_argument','argument':'connector_id'},{'verified':False,'reason':'invalid_arguments'})
            else:
                value=agent.connectors.inspect(cid,owner_user_id=goal.user_id);obs=ToolObservation(value.get('connector_id')==cid,step.preferred_tool,value,{'verified':value.get('connector_id')==cid and value.get('owner_user_id',goal.user_id)==goal.user_id,'method':'owner-scoped connector state reread','connector_id':cid})
        elif step.preferred_tool=='connector_capabilities' and agent.connectors is not None:
            cid=str(step.arguments.get('connector_id',''))
            if not cid:
                obs=ToolObservation(False,step.preferred_tool,{'error':'missing_required_argument','argument':'connector_id'},{'verified':False,'reason':'invalid_arguments'})
            else:
                value={'connector_id':cid,'capabilities':agent.connectors.capabilities(cid)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':bool(value['capabilities']),'method':'typed connector descriptor reread','connector_id':cid})
        elif step.preferred_tool=='connector_health' and agent.connectors is not None:
            cid=str(step.arguments.get('connector_id',''))
            if not cid:
                obs=ToolObservation(False,step.preferred_tool,{'error':'missing_required_argument','argument':'connector_id'},{'verified':False,'reason':'invalid_arguments'})
            else:
                value=agent.connectors.health(cid,owner_user_id=goal.user_id);obs=ToolObservation(True,step.preferred_tool,value,{'verified':value.get('connector_id')==cid and value.get('owner_user_id')==goal.user_id,'method':'connector adapter health recheck or explicit unavailable state','connector_id':cid})
        elif step.preferred_tool in {'connector_read','connector_invoke'} and agent.connectors is not None:
            cid=str(step.arguments.get('connector_id',''));op=str(step.arguments.get('operation',''));args=dict(step.arguments.get('arguments') or {});classification=str(step.arguments.get('classification','PRIVATE'));device_id=step.arguments.get('device_id');approval=agent._approval_for(goal_id,step.step_id) if step.preferred_tool=='connector_invoke' else None
            try:
                fn=agent.connectors.invoke_read if step.preferred_tool=='connector_read' else agent.connectors.invoke
                value=fn(cid,op,args,owner_user_id=goal.user_id,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,classification=classification,approval=approval,device_id=device_id);verified=bool((value.get('verification') or {}).get('verified'));obs=ToolObservation(verified,step.preferred_tool,value,value.get('verification') or {'verified':False,'reason':'connector_verification_missing'})
                agent.store.event(goal_id,'connector_invoked',{'connector_id':cid,'operation':op,'request_id':value.get('request_id'),'status':value.get('status'),'verified':verified},now());agent.traces.record('connector',cid,str(value.get('status','FAILED')),goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'request_id':value.get('request_id')},detail={'operation':op,'verified':verified,'read_only':step.preferred_tool=='connector_read'})
            except Exception as exc:
                obs=ToolObservation(False,step.preferred_tool,{'error':'connector_invocation_failed','error_type':type(exc).__name__},{'verified':False,'method':'connector manager policy/authorization/invocation/verification boundary','reason':str(getattr(exc,'category',type(exc).__name__))})
        elif step.preferred_tool in {'notification_inspect','notification_explain'} and agent.notifications is not None:
            nid=str(step.arguments.get('notification_id',''))
            if not nid:
                obs=ToolObservation(False,step.preferred_tool,{'error':'missing_required_argument','argument':'notification_id'},{'verified':False,'reason':'invalid_arguments'})
            else:
                value=agent.notifications.inspect(nid,owner_user_id=goal.user_id) if step.preferred_tool=='notification_inspect' else agent.notifications.explain(nid,owner_user_id=goal.user_id);obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped notification intelligence reread','notification_id':nid})
        elif step.preferred_tool=='notification_delivery_inspect' and agent.notification_delivery is not None:
            value=agent.notification_delivery.inspect(owner_user_id=goal.user_id,notification_id=step.arguments.get('notification_id'),attempt_id=step.arguments.get('attempt_id'));obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped delivery state reread'})
        elif step.preferred_tool=='notification_channels_inspect' and agent.notification_delivery is not None:
            value={'channels':agent.notification_delivery.channel_states(goal.user_id)};obs=ToolObservation(True,step.preferred_tool,value,{'verified':True,'method':'persisted owner-scoped channel state reread'})
        elif step.preferred_tool=='notification_delivery_retry' and agent.notification_delivery is not None:
            attempt_id=str(step.arguments.get('attempt_id',''));value=agent.notification_delivery.retry(attempt_id,owner_user_id=goal.user_id);reread=agent.store.notification_delivery_attempt(value['attempt_id']);verified=bool(reread and reread.get('notification_id')==value.get('notification_id'));obs=ToolObservation(verified,step.preferred_tool,reread or value,{'verified':verified,'method':'authorized retry + persisted delivery reread','attempt_id':value.get('attempt_id')})
        elif step.preferred_tool=='notification_acknowledge' and agent.notification_delivery is not None:
            attempt_id=str(step.arguments.get('attempt_id',''));value=agent.notification_delivery.acknowledge(attempt_id,owner_user_id=goal.user_id);reread=agent.store.notification_delivery_attempt(attempt_id);verified=bool(reread and reread.get('status')=='ACKNOWLEDGED');obs=ToolObservation(verified,step.preferred_tool,reread or value,{'verified':verified,'method':'authorized acknowledgement + persisted delivery reread','attempt_id':attempt_id})
        elif step.preferred_tool=='operations_snapshot' and agent.operations is not None:
            value=agent.operations.invoke(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
        elif step.preferred_tool.startswith('daily_brief_') and agent.daily_os is not None:
            value=agent.daily_os.invoke(step.preferred_tool,step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
        elif step.preferred_tool=='perception_observe' and agent.perception is not None:
            robot_id=str(step.arguments.get('robot_id',''));value=agent.perception.observe(robot_id);oid=value.get('observation',{}).get('observation_id');freshness=value.get('freshness',{}).get('state');verified=value.get('status')=='OBSERVED' and freshness=='FRESH' and value.get('fusion',{}).get('status')=='CURRENT';obs=ToolObservation(verified,step.preferred_tool,value,{'verified':verified,'method':'normalized perception + persisted observation + freshness/fusion check','observation_id':oid,'robot_id':robot_id,'freshness':freshness})
            if oid:
                agent.store.event(goal_id,'perception_observed',{'observation_id':oid,'robot_id':robot_id,'freshness':freshness,'source':value.get('observation',{}).get('source')},now());agent.traces.record('perception','perception_observe','OBSERVED' if verified else 'UNVERIFIED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'step_id':step.step_id,'observation_id':oid,'robot_id':robot_id},detail={'freshness':freshness,'source':value.get('observation',{}).get('source')})
        elif step.preferred_tool=='ros2_sim_move' and agent.perception is not None:
            try:agent.perception.require_fresh('turtle1')
            except Exception as exc:obs=ToolObservation(False,step.preferred_tool,{'error':'fresh perception required before simulated movement','error_type':type(exc).__name__},{'verified':False,'reason':'fresh_perception_required'})
            else:obs=agent.gen1.invoke(step.preferred_tool,step.arguments)
        elif step.preferred_tool=='image_generate' and agent.images is not None:
            try:
                value=agent.images.invoke(step.arguments,user_id=goal.user_id,goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,step_id=step.step_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
            except Exception as exc:
                obs=ToolObservation(False,step.preferred_tool,{'error':'image_generation_failed','error_type':type(exc).__name__},{'verified':False,'method':'image generation requires routed provider plus independently verified artifact','reason':type(exc).__name__})
            if obs.verification.get('verified') and obs.output.get('artifact_id') is not None:
                ref='artifact:'+str(obs.output['artifact_id'])
                if ref not in run.artifacts:run.artifacts.append(ref)
        elif step.preferred_tool=='document_ingest' and agent.documents is not None:
            value=agent.documents.invoke_ingest(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
        elif step.preferred_tool=='document_search' and agent.documents is not None:
            value=agent.documents.invoke_search(step.arguments,user_id=goal.user_id);obs=ToolObservation(bool(value['verification'].get('verified')),step.preferred_tool,value['output'],value['verification'])
        elif step.preferred_tool=='workspace_test':
            try:
                approval=agent._approval_for(goal_id,step.step_id);scope=json.dumps({'user_id':goal.user_id,'goal_id':goal_id,'tool':'workspace_test','arguments':step.arguments},sort_keys=True,separators=(',',':'),ensure_ascii=False)
                center,grant=agent._workspace_test_execution_grant(goal,run,step,approval,scope)
                if center.authorize(goal.user_id,'workspace_test',scope)!=PermissionEffect.ALLOW:raise PermissionError('workspace_test execution grant authorization failed')
                center.revoke(grant.permission_id,actor='workspace_test_consumer');agent.store.event(goal_id,'workspace_test_grant_consumed',{'permission_id':grant.permission_id,'approval_id':approval.approval_id,'step_id':step.step_id},now());agent.traces.record('authorization','workspace_test_grant','CONSUMED',goal_id=goal_id,task_run_id=run.task_run_id,trace_id=trace_id,correlation={'approval_id':approval.approval_id,'permission_id':grant.permission_id,'step_id':step.step_id},detail={'one_time':True})
                trusted_arguments={'project_name':str(step.arguments['project_name']),'approved':True};obs=agent.gen1.invoke(step.preferred_tool,trusted_arguments)
            except Exception as exc:
                obs=ToolObservation(False,step.preferred_tool,{'error':'workspace_test_authorization_failed','error_type':type(exc).__name__},{'verified':False,'reason':'workspace_test_execution_grant_failed'})
        else:
            obs=agent.gen1.invoke(step.preferred_tool,step.arguments)
        return obs
