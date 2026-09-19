import json,os,tempfile,unittest,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from sparkle.contracts import ModelResponse,ToolCall
from sparkle.model import ModelAdapter
from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.delegation import DelegationRequest,SpecialistDelegationService
from sparkle_gen2.gen1 import LocalGen1Gateway,ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

PROJECT='verifyapp'
GOOD_FILES={'src/example.py':'VALUE = 7\n','config/example.json':'{"mode":"bounded"}\n','web/example.js':'const x = 7;\n'}
CHECKS=[{'type':'python_compile','path':'src/example.py'},{'type':'json_parse','path':'config/example.json'}]

class VerifyAdapter(ModelAdapter):
    provider='verify-test';model_id='verify-test'
    def __init__(self,tool_args=None,*,skip_tool=False):self.calls=0;self.requests=[];self.tool_args=tool_args;self.skip_tool=skip_tool
    def complete(self,request):
        self.calls+=1;self.requests.append(request)
        if self.calls==1 and not self.skip_tool:
            args=dict(self.tool_args or {'project_name':PROJECT,'checks':[dict(x) for x in CHECKS],'approved':True})
            return ModelResponse('',self.model_id,self.provider,'tool_use',[ToolCall('verify-1','workspace_verify',args)])
        return ModelResponse('The approved workspace verification completed.',self.model_id,self.provider,'stop')
    def health(self):return {'configured':True}

class TamperEvidenceGateway(LocalGen1Gateway):
    def __init__(self,system):super().__init__(system);self.tool_return=None
    def verify_delegated_action(self,tool,arguments,output):
        if tool=='workspace_verify':
            self.tool_return=dict(output);vid=output.get('verification_id')
            fake=[{'type':'python_compile','path':'src/other.py','status':'passed','output':'Python source compiled without execution'}]
            with self.system.development.connect() as db:db.execute('UPDATE verification_runs SET checks_json=?,passed=?,failed=?,status=? WHERE id=?',(json.dumps(fake,separators=(',',':')),1,0,'passed',vid))
        return super().verify_delegated_action(tool,arguments,output)

def actual_gateway(adapter,cls=LocalGen1Gateway):
    registry=ModelRegistry();registry.inject(registry.active_id,adapter);return cls(SparkleSystem(model_registry=registry))

def verify_plan(project=PROJECT,checks=None,specialist='application_builder'):
    args={'project_name':project,'checks':[dict(x) for x in (CHECKS if checks is None else checks)]}
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('delegate','Perform exactly the approved static workspace verification',['specialist_delegate'],[],['persisted verification evidence exactly matches approved checks'],{'specialists':[specialist],'objective':'Run exactly the approved bounded workspace verification checks','authorized_action':{'tool':'workspace_verify','arguments':args},'required_evidence':['persisted verification run reread']},30,0)],[{'description':'approved workspace verification independently verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],'test-only')

def direct_plan():
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Calculate directly',['calculator'],[],['verified'],{'expression':'700+3'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test-only')

class DirectGateway:
    def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
    def retrieve_context(self,*a):return {'source':'test','rendered':'bounded'}
    def invoke(self,tool,args):return ToolObservation(True,tool,{'value':703},{'verified':True,'method':'test calculator'})

class Cycle49WorkspaceVerifyDelegationTests(unittest.TestCase):
    def _env(self,d):
        env=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')});env.start();self.addCleanup(env.stop);Path(os.environ['SPARKLE_DATA_DIR']).mkdir(exist_ok=True)
    def _start(self,d,adapter=None,*,plan=None,gateway_cls=LocalGen1Gateway,user='verify-user',files=None,max_replans=0):
        self._env(d);adapter=adapter or VerifyAdapter();gateway=actual_gateway(adapter,gateway_cls);gateway.system.workspaces.scaffold(PROJECT,dict(GOOD_FILES if files is None else files));db=Path(d)/'g2.db';agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(plan or verify_plan()),max_replans=max_replans);first=agent.start('Verify the approved bounded workspace checks.',user_id=user);return db,gateway,adapter,agent,first
    def _approve_resume(self,agent,first,actor='human-reviewer'):
        self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);agent.decide_approval(first['approvals'][0],'approve',actor=actor);return agent.resume(first['goal_id'])

    def test_valid_approved_workspace_verify_exact_checks_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            db,g,a,agent,first=self._start(d);self.assertEqual(a.calls,0);final=self._approve_resume(agent,first);self.assertEqual(final['status'],'COMPLETED');self.assertEqual(a.calls,2)
            record=final['delegations'][0];grant=agent.delegation.grants.load(record['request']['grant_id']);self.assertEqual((grant.state,grant.uses),('CONSUMED',1));self.assertEqual(grant.scope['arguments'],{'project_name':PROJECT,'checks':CHECKS});self.assertEqual(grant.allowed_specialists,['application_builder']);self.assertEqual(grant.allowed_tools,['workspace_verify'])
            runs=g.system.development.list(limit=100);self.assertEqual(len(runs),1);self.assertEqual([{'type':x['type'],'path':x['path']} for x in runs[0]['checks']],CHECKS);self.assertEqual(runs[0]['status'],'passed')
            verification=record['result']['verification']['authorized_action_verification'][0]['verification'];self.assertTrue(verification['verified']);self.assertEqual(verification['expected_checks'],CHECKS);self.assertEqual(verification['persisted_checks'],CHECKS);self.assertEqual(verification['returned_checks'],CHECKS)
            events=[x['event_type'] for x in Gen2Store(db).events(first['goal_id'])];self.assertIn('delegation_grant_issued',events);self.assertIn('delegation_grant_consumed',events);self.assertIn('goal_completed',events)
            traces=Gen2Store(db).operation_traces(trace_id=first['trace_id']);self.assertTrue(any(t['kind']=='authorization' and t['status']=='CONSUMED' for t in traces));self.assertTrue(any(t['kind']=='verification' and t['status']=='VERIFIED' for t in traces));self.assertTrue(all(r.metadata.get('user_id')=='verify-user' for r in a.requests))

    def test_no_approval_or_model_fake_approval_means_no_execution(self):
        with tempfile.TemporaryDirectory() as d:
            fake={'project_name':PROJECT,'checks':[dict(x) for x in CHECKS],'approved':True,'approval_id':'model-forged'};_,g,a,_,first=self._start(d,VerifyAdapter(fake));self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,0);self.assertEqual(g.system.development.list(limit=100),[])

    def test_project_check_type_path_added_removed_and_changed_scope_are_denied(self):
        mutations=[
            {'project_name':'otherapp','checks':[dict(x) for x in CHECKS],'approved':True},
            {'project_name':PROJECT,'checks':[{'type':'json_parse','path':'src/example.py'},CHECKS[1]],'approved':True},
            {'project_name':PROJECT,'checks':[{'type':'python_compile','path':'web/example.js'},CHECKS[1]],'approved':True},
            {'project_name':PROJECT,'checks':[dict(x) for x in CHECKS]+[{'type':'javascript_syntax','path':'web/example.js'}],'approved':True},
            {'project_name':PROJECT,'checks':[dict(CHECKS[0])],'approved':True},
        ]
        for tool_args in mutations:
            with self.subTest(tool_args=tool_args),tempfile.TemporaryDirectory() as d:
                _,g,_,agent,first=self._start(d,VerifyAdapter(tool_args));result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');self.assertEqual(g.system.development.list(limit=100),[])

    def test_wrong_specialist_capability_tool_user_and_goal_grant_checks_fail(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id);req=agent.delegation.load(record.request.request_id).request
            cases=[
                (req,'research','workspace_verify','workspace_verify',grant.scope['arguments'],'specialist mismatch'),
                (req,'application_builder','workspace_test','workspace_verify',grant.scope['arguments'],'tool mismatch'),
                (req,'application_builder','workspace_verify','workspace_test',grant.scope['arguments'],'capability mismatch'),
                (DelegationRequest(**(req.to_dict()|{'user_id':'other-user'})),'application_builder','workspace_verify','workspace_verify',grant.scope['arguments'],'parent correlation'),
                (DelegationRequest(**(req.to_dict()|{'goal_id':'other-goal'})),'application_builder','workspace_verify','workspace_verify',grant.scope['arguments'],'parent correlation'),
            ]
            for r,specialist,tool,cap,args,reason in cases:
                with self.subTest(reason=reason),self.assertRaisesRegex(PermissionError,reason):agent.delegation.grants.check(grant.grant_id,request=r,specialist=specialist,tool=tool,capability=cap,arguments=args)

    def test_other_verify_capable_specialists_are_rejected(self):
        for specialist in ('ai_builder','agent_builder'):
            with self.subTest(specialist=specialist),tempfile.TemporaryDirectory() as d:
                _,g,a,_,result=self._start(d,plan=verify_plan(specialist=specialist));self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(a.calls,0);self.assertEqual(g.system.development.list(limit=100),[])

    def test_path_traversal_absolute_backslash_invalid_type_and_malformed_checks_rejected_before_approval(self):
        bad=[
            [{'type':'python_compile','path':'../outside.py'}],
            [{'type':'python_compile','path':'/tmp/outside.py'}],
            [{'type':'python_compile','path':'src\\example.py'}],
            [{'type':'pytest','path':'src/example.py'}],
            [{'type':'python_compile','path':'src/example.py','extra':True}],
            [],
        ]
        for checks in bad:
            with self.subTest(checks=checks),tempfile.TemporaryDirectory() as d:
                _,g,a,_,result=self._start(d,plan=verify_plan(checks=checks));self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(a.calls,0);self.assertEqual(g.system.development.list(limit=100),[])

    def test_symlink_check_path_is_denied_before_grant_consumption(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);project=g.system.workspaces.root/PROJECT;outside=Path(d)/'outside.py';outside.write_text('VALUE=1\n');(project/'src/example.py').unlink();(project/'src/example.py').symlink_to(outside);result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual(grant.state,'ACTIVE');self.assertEqual(g.system.development.list(limit=100),[])

    def test_verification_failure_is_persisted_but_parent_never_completes(self):
        with tempfile.TemporaryDirectory() as d:
            broken=dict(GOOD_FILES);broken['src/example.py']='def broken(:\n';_,g,_,agent,first=self._start(d,files=broken);result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');runs=g.system.development.list(limit=100);self.assertEqual(len(runs),1);self.assertEqual(runs[0]['status'],'failed');self.assertEqual(runs[0]['failed'],1);self.assertFalse(result['delegations'][0]['result']['verification']['verified'])

    def test_execution_failure_consumes_grant_and_never_completes(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);original=g.system.development.verify
            def fail(project,checks):raise RuntimeError('controlled verification execution failure')
            g.system.development.verify=fail
            try:result=self._approve_resume(agent,first)
            finally:g.system.development.verify=original
            self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual((grant.state,grant.uses),('CONSUMED',1));self.assertEqual(g.system.development.list(limit=100),[])

    def test_tool_success_but_persisted_reread_mismatch_prevents_completion(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d,gateway_cls=TamperEvidenceGateway);result=self._approve_resume(agent,first);self.assertEqual(g.tool_return['status'],'passed');self.assertNotEqual(result['status'],'COMPLETED');runs=g.system.development.list(limit=100);self.assertEqual(runs[0]['status'],'passed');self.assertNotEqual([{'type':x['type'],'path':x['path']} for x in runs[0]['checks']],CHECKS);self.assertFalse(result['delegations'][0]['result']['verification']['verified']);self.assertIn('delegated_action_independent_verification_failed',str(result['delegations'][0]['result']['failure']))

    def test_persisted_grant_restart_executes_and_expired_or_consumed_restart_denies(self):
        with tempfile.TemporaryDirectory() as d:
            db,g,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id)
            restarted=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=restarted.load(record.request.request_id).request;result=restarted.execute(req);self.assertEqual(result.status,'COMPLETED');self.assertTrue(result.verification['verified']);self.assertEqual(restarted.grants.load(grant.grant_id).state,'CONSUMED');self.assertEqual(len(g.system.development.list(limit=100)),1)
            restarted2=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine())
            with self.assertRaisesRegex(PermissionError,'not active'):restarted2.grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_verify',capability='workspace_verify',arguments=grant.scope['arguments'])
        with tempfile.TemporaryDirectory() as d:
            db,g,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id);grant.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();grant.fingerprint=agent.delegation.grants.fingerprint(grant);agent.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict());restarted=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=restarted.load(record.request.request_id).request
            with self.assertRaisesRegex(PermissionError,'expired'):restarted.grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_verify',capability='workspace_verify',arguments=grant.scope['arguments'])

    def test_reobserve_completed_goal_does_not_run_second_verification(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,a,agent,first=self._start(d);final=self._approve_resume(agent,first);self.assertEqual(final['status'],'COMPLETED');runs=len(g.system.development.list(limit=100));calls=a.calls;again=agent.resume(first['goal_id']);self.assertEqual(again['status'],'COMPLETED');self.assertEqual(len(g.system.development.list(limit=100)),runs);self.assertEqual(a.calls,calls)

    def test_direct_workspace_verify_and_direct_calculator_remain_nondelegated(self):
        with tempfile.TemporaryDirectory() as d:
            self._env(d);g=LocalGen1Gateway(SparkleSystem());g.system.workspaces.scaffold(PROJECT,dict(GOOD_FILES));obs=g.invoke('workspace_verify',{'project_name':PROJECT,'checks':[dict(x) for x in CHECKS],'approved':True});self.assertTrue(obs.ok);self.assertTrue(obs.verification['verified']);self.assertIn('verification run',obs.verification['method'])
        with tempfile.TemporaryDirectory() as d:
            result=PersonalAgent(Gen2Store(Path(d)/'g.db'),DirectGateway(),planner=StaticPlanner(direct_plan())).start('Calculate 700 + 3.');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['delegations'],[]);self.assertIn('703',result['text'])

if __name__=='__main__':unittest.main()
