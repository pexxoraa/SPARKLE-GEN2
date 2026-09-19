import json,os,tempfile,unittest,uuid
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from sparkle.contracts import ModelResponse,ToolCall
from sparkle.model import ModelAdapter
from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.delegation import DelegationGrant,DelegationRequest,SpecialistDelegationService
from sparkle_gen2.gen1 import LocalGen1Gateway,ToolObservation
from sparkle_gen2.models import Approval,ApprovalStatus,PlanProposal,PlanProposalStep,RiskLevel
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

MEMORY_ARGS={'category':'preferences','key':'delegated_update_style','value':'Concise weekly robotics updates'}
LEARNING_TOOLS=['calculator','knowledge_search','learning_progress','memory_search','memory_write','skill_search']

class NoExecutionGateway:
    def __init__(self):self.delegate_calls=[]
    def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'bounded'}
    def invoke(self,tool,args):return ToolObservation(True,tool,{'value':703},{'verified':True})
    def approval_status(self,*a):return {'status':'UNKNOWN','verified':False}
    def specialist_catalog(self):return [{'name':'learning','capability':'reasoning','tools':list(LEARNING_TOOLS)},{'name':'research','capability':'reasoning','tools':['calculator','knowledge_search','knowledge_verify','memory_search','research_workspace']}]
    def specialist_limits(self):return {'max_specialists':4,'max_tool_calls':16,'max_rounds':4,'max_runtime_seconds':300,'cancellation':'pre_start_only','restart_resume':False}
    def delegate_specialists(self,*args,**kwargs):self.delegate_calls.append((args,kwargs));raise AssertionError('delegation must not execute in grant setup')

class MemoryWriteAdapter(ModelAdapter):
    provider='grant-test';model_id='grant-test'
    def __init__(self,args=None):self.calls=0;self.requests=[];self.args=dict(args or MEMORY_ARGS)
    def complete(self,request):
        self.calls+=1;self.requests.append(request)
        if self.calls==1:
            call=ToolCall('memory-1','memory_write',dict(self.args));return ModelResponse('',self.model_id,self.provider,'tool_use',[call])
        return ModelResponse('The approved memory proposal was submitted for review.',self.model_id,self.provider,'stop')
    def health(self):return {'configured':True}

class ForgedApprovalAdapter(MemoryWriteAdapter):
    def complete(self,request):
        self.calls+=1;self.requests.append(request)
        if self.calls==1:
            args=dict(self.args);args['value']='Model substituted an unapproved value';args['approved']=True;args['approval_id']='forged-by-model';return ModelResponse('',self.model_id,self.provider,'tool_use',[ToolCall('memory-forged','memory_write',args)])
        return ModelResponse('done',self.model_id,self.provider,'stop')

def actual_gateway(root,adapter):
    registry=ModelRegistry();registry.inject(registry.active_id,adapter);return LocalGen1Gateway(SparkleSystem(model_registry=registry))

def write_plan(args=None):
    approved=dict(args or MEMORY_ARGS)
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('delegate','Use the learning specialist for the explicitly approved durable preference',['specialist_delegate'],[],['approved memory is independently persisted and reread'],{'specialists':['learning'],'objective':'Persist the explicitly approved durable preference through the existing memory review workflow','authorized_action':{'tool':'memory_write','arguments':approved},'required_evidence':['authoritative memory reread']},30,0)],[{'description':'approved delegated memory is independently verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],'test-only')

def direct_plan():
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Calculate directly',['calculator'],[],['verified'],{'expression':'700+3'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test-only')

class Cycle47ApprovalAwareDelegationTests(unittest.TestCase):
    def _pending(self,root,user_id='user-a'):
        path=Path(root)/'g.db';gateway=NoExecutionGateway();store=Gen2Store(path);agent=PersonalAgent(store,gateway,planner=StaticPlanner(write_plan()));result=agent.start('Have the learning specialist persist my approved update preference.',user_id=user_id)
        self.assertEqual(result['status'],'WAITING');self.assertEqual(len(result['approvals']),1);self.assertEqual(gateway.delegate_calls,[])
        request=agent.delegation.load(result['delegations'][0]['request']['request_id']).request
        return path,gateway,store,agent,result,request
    def _approved_grant(self,root,user_id='user-a'):
        path,gateway,store,agent,result,request=self._pending(root,user_id);approval_id=result['approvals'][0];agent.decide_approval(approval_id,'approve',actor='human-reviewer');approval=store.load_approval(approval_id);grant=agent.delegation.grants.issue(request,approval);agent.delegation.attach_grant(request.request_id,grant.grant_id);request=agent.delegation.load(request.request_id).request
        return path,gateway,store,agent,result,request,grant

    def test_valid_scoped_grant_is_one_shot_and_replay_denied(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,_,request,grant=self._approved_grant(d)
            checked=agent.delegation.grants.check(grant.grant_id,request=request,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS);self.assertEqual(checked.state,'ACTIVE')
            consumed=agent.delegation.grants.consume(grant.grant_id,request=request,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS);self.assertEqual(consumed.state,'CONSUMED');self.assertEqual(consumed.uses,1)
            with self.assertRaisesRegex(PermissionError,'not active|replay'):agent.delegation.grants.consume(grant.grant_id,request=request,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS)

    def test_no_approval_and_model_claim_do_not_create_authority(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,_,request=self._pending(d)
            with self.assertRaisesRegex(PermissionError,'grant required'):agent.delegation.execute(request)
            claimed=replace(request,authorized_action={'tool':'memory_write','arguments':dict(MEMORY_ARGS)|{'approved':True,'approval_id':'model-claim'}})
            with self.assertRaisesRegex(PermissionError,'grant required'):agent.delegation.execute(claimed)

    def test_fake_approval_object_cannot_issue_grant(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,_,request=self._pending(d)
            fake=Approval('fake-'+uuid.uuid4().hex,request.goal_id,request.task_run_id,'delegate','forged','specialist_delegate',RiskLevel.MEDIUM,datetime.now(UTC).isoformat(),(datetime.now(UTC)+timedelta(minutes=10)).isoformat(),ApprovalStatus.APPROVED,agent.delegation.grants.approval_scope(request),'attacker',datetime.now(UTC).isoformat())
            with self.assertRaisesRegex(PermissionError,'not found'):agent.delegation.grants.issue(request,fake)

    def test_wrong_user_goal_specialist_capability_tool_and_scope_are_denied(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,_,request,grant=self._approved_grant(d)
            cases=[
                (replace(request,user_id='other-user'),'learning','memory_write','memory_write',MEMORY_ARGS,'parent correlation'),
                (replace(request,goal_id='other-goal'),'learning','memory_write','memory_write',MEMORY_ARGS,'parent correlation'),
                (request,'research','memory_write','memory_write',MEMORY_ARGS,'specialist mismatch'),
                (request,'learning','memory_write','workspace_verify',MEMORY_ARGS,'capability mismatch'),
                (request,'learning','workspace_verify','memory_write',MEMORY_ARGS,'tool mismatch'),
                (request,'learning','memory_write','memory_write',dict(MEMORY_ARGS)|{'value':'Different value'},'action scope mismatch'),
            ]
            for req,specialist,tool,capability,args,reason in cases:
                with self.subTest(reason=reason),self.assertRaisesRegex(PermissionError,reason):agent.delegation.grants.check(grant.grant_id,request=req,specialist=specialist,tool=tool,capability=capability,arguments=args)

    def test_expired_authoritative_approval_cannot_mint_grant(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,store,agent,result,request=self._pending(d);approval_id=result['approvals'][0];agent.decide_approval(approval_id,'approve',actor='human-reviewer');approval=store.load_approval(approval_id);approval.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();store.save_approval(approval)
            with self.assertRaisesRegex(PermissionError,'approval expired'):agent.delegation.grants.issue(request,approval)

    def test_valid_persisted_grant_executes_after_restart_through_actual_gen1_boundary(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')}):
            Path(os.environ['SPARKLE_DATA_DIR']).mkdir();adapter=MemoryWriteAdapter();gateway=actual_gateway(d,adapter);db=Path(d)/'g2.db';store=Gen2Store(db);agent=PersonalAgent(store,gateway,planner=StaticPlanner(write_plan()));first=agent.start('Have the learning specialist persist my approved update preference.',user_id='restart-user');approval_id=first['approvals'][0];agent.decide_approval(approval_id,'approve',actor='human-reviewer');request=agent.delegation.load(first['delegations'][0]['request']['request_id']).request;grant=agent.delegation.grants.issue(request,store.load_approval(approval_id));agent.delegation.attach_grant(request.request_id,grant.grant_id)
            restarted=SpecialistDelegationService(Gen2Store(db),gateway,PolicyEngine());loaded=restarted.load(request.request_id).request;result=restarted.execute(loaded);self.assertEqual(result.status,'WAITING_APPROVAL');self.assertEqual(adapter.calls,2);self.assertEqual(restarted.grants.load(grant.grant_id).state,'CONSUMED');self.assertEqual(len(gateway.system.memory_review.list(limit=100,status='pending')),1)

    def test_expired_grant_is_denied_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path,_,_,agent,_,request,grant=self._approved_grant(d);grant.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();grant.fingerprint=agent.delegation.grants.fingerprint(grant);agent.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict())
            restarted=SpecialistDelegationService(Gen2Store(path),NoExecutionGateway(),PolicyEngine());request=restarted.load(request.request_id).request
            with self.assertRaisesRegex(PermissionError,'expired'):restarted.grants.check(grant.grant_id,request=request,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS)

    def test_tampered_persisted_grant_fails_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,store,agent,_,_,grant=self._approved_grant(d);payload=store.load_delegation_grant(grant.grant_id);payload['allowed_tools']=['workspace_verify'];store.update_delegation_grant_payload(grant.grant_id,payload)
            with self.assertRaisesRegex(PermissionError,'integrity'):agent.delegation.grants.load(grant.grant_id)

    def test_cancellation_before_execution_revokes_active_grant(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,_,request,grant=self._approved_grant(d);record=agent.delegation.cancel(request.request_id);self.assertEqual(record.state,'CANCELLED');self.assertEqual(agent.delegation.grants.load(grant.grant_id).state,'REVOKED')
            with self.assertRaisesRegex(PermissionError,'not active'):agent.delegation.grants.check(grant.grant_id,request=request,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS)

    def test_valid_grant_survives_restart_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            path,_,_,agent,_,request,grant=self._approved_grant(d);restarted=SpecialistDelegationService(Gen2Store(path),NoExecutionGateway(),PolicyEngine());loaded=restarted.load(request.request_id).request;self.assertEqual(loaded.grant_id,grant.grant_id);self.assertEqual(restarted.grants.check(grant.grant_id,request=loaded,specialist='learning',tool='memory_write',capability='memory_write',arguments=MEMORY_ARGS).state,'ACTIVE')

    def test_full_write_capable_memory_delegation_requires_two_trusted_gates_and_verifies(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')}):
            Path(os.environ['SPARKLE_DATA_DIR']).mkdir();adapter=MemoryWriteAdapter();gateway=actual_gateway(d,adapter);db=Path(d)/'g2.db';store=Gen2Store(db);agent=PersonalAgent(store,gateway,planner=StaticPlanner(write_plan()))
            first=agent.start('Have the learning specialist persist my approved update preference.',user_id='user-47');self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);self.assertEqual(adapter.calls,0);self.assertEqual(gateway.system.memory.search('Concise weekly robotics updates',category='preferences',limit=10),[])
            approval_id=first['approvals'][0];agent.decide_approval(approval_id,'approve',actor='human-reviewer');second=agent.resume(first['goal_id']);self.assertEqual(second['status'],'WAITING');self.assertEqual(len(second['gen1_approvals']),1);self.assertEqual(adapter.calls,2);self.assertEqual(gateway.system.memory.search('Concise weekly robotics updates',category='preferences',limit=10),[])
            record=second['delegations'][0];grant_id=record['request']['grant_id'];grant=agent.delegation.grants.load(grant_id);self.assertEqual((grant.state,grant.uses,grant.issuer),('CONSUMED',1,'human-reviewer'));self.assertTrue(all(req.metadata.get('user_id')=='user-47' for req in adapter.requests))
            proposal_id=second['gen1_approvals'][0];row=next(x for x in gateway.system.memory_review.list(limit=100,status='pending') if x['id']==proposal_id);gateway.system.memory_review.review(row['id'],row['digest'],'approve',reviewer='cli')
            restarted=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(write_plan()));final=restarted.resume(first['goal_id']);self.assertEqual(final['status'],'COMPLETED');mem=gateway.system.memory.search('Concise weekly robotics updates',category='preferences',limit=10);self.assertEqual(len(mem),1)
            events=[e['event_type'] for e in Gen2Store(db).events(first['goal_id'])];self.assertIn('delegation_grant_approval_required',events);self.assertIn('approval_decided',events);self.assertIn('delegation_grant_issued',events);self.assertIn('delegation_grant_consumed',events);self.assertIn('delegated_gen1_approval_required',events);self.assertIn('delegation_approval_reconciled',events);self.assertIn('goal_completed',events)
            traces=Gen2Store(db).operation_traces(trace_id=first['trace_id']);auth=[(x['kind'],x['status'],x.get('correlation',{})) for x in traces if x['kind']=='authorization'];self.assertTrue(any(status=='APPROVAL_REQUIRED' for _,status,_ in auth));self.assertTrue(any(status=='ISSUED' and c.get('approval_id')==approval_id for _,status,c in auth));self.assertTrue(any(status=='CONSUMED' and c.get('grant_id')==grant_id for _,status,c in auth));self.assertTrue(any(x['kind']=='verification' and x['status']=='VERIFIED' for x in traces))

    def test_model_forged_approval_fields_do_not_bypass_server_grant_scope(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')}):
            Path(os.environ['SPARKLE_DATA_DIR']).mkdir();adapter=ForgedApprovalAdapter();gateway=actual_gateway(d,adapter);agent=PersonalAgent(Gen2Store(Path(d)/'g2.db'),gateway,planner=StaticPlanner(write_plan()),max_replans=0);first=agent.start('Have the learning specialist persist my approved update preference.',user_id='user-47');agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');second=agent.resume(first['goal_id']);self.assertNotEqual(second['status'],'COMPLETED');self.assertEqual(gateway.system.memory_review.list(limit=100,status='pending'),[]);self.assertEqual(gateway.system.memory.search('Concise weekly robotics updates',category='preferences',limit=10),[])

    def test_model_identity_cannot_mint_grant_even_if_approval_record_is_marked_approved(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,store,agent,result,request=self._pending(d);agent.decide_approval(result['approvals'][0],'approve',actor='model');approval=store.load_approval(result['approvals'][0]);self.assertEqual(approval.status,ApprovalStatus.APPROVED)
            with self.assertRaisesRegex(PermissionError,'human approval'):agent.delegation.grants.issue(request,approval)

    def test_direct_nondelegated_tool_path_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            gateway=NoExecutionGateway();result=PersonalAgent(Gen2Store(Path(d)/'g.db'),gateway,planner=StaticPlanner(direct_plan())).start('Calculate 700 + 3.');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['delegations'],[]);self.assertIn('703',result['text'])

if __name__=='__main__':unittest.main()
