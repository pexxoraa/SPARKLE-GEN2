import os,tempfile,unittest,uuid
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

PROJECT='scaffoldapp'
FILES={'config/example.txt':'mode=bounded\n','src/example.py':'VALUE = 7\n'}

class ScaffoldAdapter(ModelAdapter):
    provider='scaffold-test';model_id='scaffold-test'
    def __init__(self,tool_args=None,*,skip_tool=False):self.calls=0;self.requests=[];self.tool_args=tool_args;self.skip_tool=skip_tool
    def complete(self,request):
        self.calls+=1;self.requests.append(request)
        if self.calls==1 and not self.skip_tool:
            args=dict(self.tool_args or {'project_name':PROJECT,'files':dict(FILES),'approved':True})
            return ModelResponse('',self.model_id,self.provider,'tool_use',[ToolCall('scaffold-1','workspace_scaffold',args)])
        return ModelResponse('The approved workspace scaffold is complete.',self.model_id,self.provider,'stop')
    def health(self):return {'configured':True}

class TamperGateway(LocalGen1Gateway):
    def verify_delegated_action(self,tool,arguments,output):
        if tool=='workspace_scaffold':
            root=(self.system.workspaces.root/str(arguments['project_name']));(root/'unauthorized.txt').write_text('tampered\n',encoding='utf-8')
        return super().verify_delegated_action(tool,arguments,output)

def actual_gateway(adapter,cls=LocalGen1Gateway):
    registry=ModelRegistry();registry.inject(registry.active_id,adapter);return cls(SparkleSystem(model_registry=registry))

def scaffold_plan(project=PROJECT,files=None,specialist='application_builder',extra_action=None):
    args={'project_name':project,'files':dict(FILES if files is None else files),'overwrite':False}
    if extra_action:args.update(extra_action)
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('delegate','Create the explicitly approved bounded application workspace',['specialist_delegate'],[],['filesystem exactly matches approved manifest'],{'specialists':[specialist],'objective':'Create exactly the approved application workspace manifest','authorized_action':{'tool':'workspace_scaffold','arguments':args},'required_evidence':['exact filesystem manifest reread']},30,0)],[{'description':'approved workspace scaffold independently verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],'test-only')

def direct_plan():
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Calculate directly',['calculator'],[],['verified'],{'expression':'700+3'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test-only')

class DirectGateway:
    def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
    def retrieve_context(self,*a):return {'source':'test','rendered':'bounded'}
    def invoke(self,tool,args):return ToolObservation(True,tool,{'value':703},{'verified':True,'method':'test calculator'})

class Cycle48WorkspaceScaffoldDelegationTests(unittest.TestCase):
    def _env(self,d):
        env=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')});env.start();self.addCleanup(env.stop);Path(os.environ['SPARKLE_DATA_DIR']).mkdir(exist_ok=True)
    def _start(self,d,adapter=None,*,plan=None,gateway_cls=LocalGen1Gateway,user='workspace-user',max_replans=0):
        self._env(d);adapter=adapter or ScaffoldAdapter();gateway=actual_gateway(adapter,gateway_cls);db=Path(d)/'g2.db';agent=PersonalAgent(Gen2Store(db),gateway,planner=StaticPlanner(plan or scaffold_plan()),max_replans=max_replans);first=agent.start('Create the approved bounded application workspace.',user_id=user);return db,gateway,adapter,agent,first
    def _approve_resume(self,agent,first,actor='human-reviewer'):
        self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);agent.decide_approval(first['approvals'][0],'approve',actor=actor);return agent.resume(first['goal_id'])

    def test_valid_approved_scaffold_exact_manifest_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            db,g,a,agent,first=self._start(d);self.assertEqual(a.calls,0);final=self._approve_resume(agent,first);self.assertEqual(final['status'],'COMPLETED');self.assertEqual(a.calls,2)
            root=(g.system.workspaces.root/PROJECT);self.assertTrue(root.is_dir());actual={p.relative_to(root).as_posix():p.read_text(encoding='utf-8') for p in root.rglob('*') if p.is_file()};self.assertEqual(actual,FILES)
            record=final['delegations'][0];grant=agent.delegation.grants.load(record['request']['grant_id']);self.assertEqual(grant.state,'CONSUMED');self.assertEqual(grant.scope['arguments'],{'project_name':PROJECT,'files':FILES,'overwrite':False});self.assertEqual(grant.allowed_specialists,['application_builder']);self.assertEqual(grant.allowed_tools,['workspace_scaffold'])
            check=record['result']['verification']['authorized_action_verification'][0]['verification'];self.assertTrue(check['verified']);self.assertEqual(check['expected_files'],sorted(FILES));self.assertEqual(check['actual_files'],sorted(FILES))
            events=[x['event_type'] for x in Gen2Store(db).events(first['goal_id'])];self.assertIn('delegation_grant_issued',events);self.assertIn('delegation_grant_consumed',events);self.assertIn('goal_completed',events)
            traces=Gen2Store(db).operation_traces(trace_id=first['trace_id']);self.assertTrue(any(t['kind']=='authorization' and t['status']=='CONSUMED' for t in traces));self.assertTrue(any(t['kind']=='verification' and t['status']=='VERIFIED' for t in traces))

    def test_no_approval_means_no_model_call_and_no_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,a,_,first=self._start(d);self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,0);self.assertFalse((g.system.workspaces.root/PROJECT).exists())

    def test_model_fake_approval_does_not_authorize_without_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            fake={'project_name':PROJECT,'files':dict(FILES),'approved':True,'approval_id':'model-forged'};_,g,a,_,first=self._start(d,ScaffoldAdapter(fake));self.assertEqual(first['status'],'WAITING');self.assertEqual(a.calls,0);self.assertFalse((g.system.workspaces.root/PROJECT).exists())

    def test_scope_mutations_workspace_file_content_and_extra_file_are_denied(self):
        mutations=[
            {'project_name':'otherapp','files':dict(FILES),'approved':True},
            {'project_name':PROJECT,'files':{'src/other.py':'VALUE = 7\n','config/example.txt':'mode=bounded\n'},'approved':True},
            {'project_name':PROJECT,'files':{'src/example.py':'VALUE = 8\n','config/example.txt':'mode=bounded\n'},'approved':True},
            {'project_name':PROJECT,'files':dict(FILES)|{'extra.txt':'not approved\n'},'approved':True},
        ]
        for tool_args in mutations:
            with self.subTest(tool_args=tool_args),tempfile.TemporaryDirectory() as d:
                _,g,_,agent,first=self._start(d,ScaffoldAdapter(tool_args));result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');self.assertFalse((g.system.workspaces.root/PROJECT).exists());self.assertFalse((g.system.workspaces.root/'otherapp').exists())

    def test_wrong_specialist_tool_capability_user_and_goal_grant_checks_fail(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,agent,first=self._start(d);approval_id=first['approvals'][0];agent.decide_approval(approval_id,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(approval_id));agent.delegation.attach_grant(record.request.request_id,grant.grant_id);req=agent.delegation.load(record.request.request_id).request
            cases=[
                (req,'research','workspace_scaffold','workspace_scaffold',grant.scope['arguments'],'specialist mismatch'),
                (req,'application_builder','workspace_verify','workspace_scaffold',grant.scope['arguments'],'tool mismatch'),
                (req,'application_builder','workspace_scaffold','workspace_verify',grant.scope['arguments'],'capability mismatch'),
                (DelegationRequest(**(req.to_dict()|{'user_id':'other-user'})),'application_builder','workspace_scaffold','workspace_scaffold',grant.scope['arguments'],'parent correlation'),
                (DelegationRequest(**(req.to_dict()|{'goal_id':'other-goal'})),'application_builder','workspace_scaffold','workspace_scaffold',grant.scope['arguments'],'parent correlation'),
            ]
            for r,specialist,tool,cap,args,reason in cases:
                with self.subTest(reason=reason),self.assertRaisesRegex(PermissionError,reason):agent.delegation.grants.check(grant.grant_id,request=r,specialist=specialist,tool=tool,capability=cap,arguments=args)

    def test_other_scaffold_capable_specialists_are_rejected_for_this_boundary(self):
        for specialist in ('ai_builder','agent_builder'):
            with self.subTest(specialist=specialist),tempfile.TemporaryDirectory() as d:
                _,g,a,_,result=self._start(d,plan=scaffold_plan(specialist=specialist));self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(a.calls,0);self.assertFalse((g.system.workspaces.root/PROJECT).exists())

    def test_path_traversal_absolute_malformed_and_overwrite_rejected_before_approval(self):
        bad_plans=[
            scaffold_plan(files={'../outside.txt':'x'}),
            scaffold_plan(files={'/tmp/outside.txt':'x'}),
            scaffold_plan(files={}),
            scaffold_plan(project='Bad Project'),
            scaffold_plan(extra_action={'overwrite':True}),
        ]
        for plan in bad_plans:
            with self.subTest(plan=plan),tempfile.TemporaryDirectory() as d:
                _,g,a,_,result=self._start(d,plan=plan);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(a.calls,0);self.assertFalse((g.system.workspaces.root/PROJECT).exists())

    def test_existing_workspace_is_denied_before_grant_consumption(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);root=g.system.workspaces.root/PROJECT;root.mkdir(parents=True);(root/'preexisting.txt').write_text('existing\n');result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual(grant.state,'ACTIVE');self.assertTrue((root/'preexisting.txt').exists())

    def test_symlink_workspace_root_is_denied_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);outside=Path(d)/'outside';outside.mkdir();root=g.system.workspaces.root/PROJECT;root.parent.mkdir(parents=True,exist_ok=True);root.symlink_to(outside,target_is_directory=True);result=self._approve_resume(agent,first);self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual(grant.state,'ACTIVE');self.assertEqual(list(outside.iterdir()),[])

    def test_execution_failure_consumes_one_shot_grant_and_never_completes(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);tool=g.system.tools._tools['workspace_scaffold']
            original=tool.run
            def fail(arguments):raise RuntimeError('controlled scaffold failure')
            tool.run=fail
            try:result=self._approve_resume(agent,first)
            finally:tool.run=original
            self.assertNotEqual(result['status'],'COMPLETED');grant=agent.delegation.grants.for_request(first['delegations'][0]['request']['request_id']);self.assertEqual((grant.state,grant.uses),('CONSUMED',1));self.assertFalse((g.system.workspaces.root/PROJECT).exists())

    def test_verification_mismatch_after_real_write_prevents_completion(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d,gateway_cls=TamperGateway);result=self._approve_resume(agent,first);root=g.system.workspaces.root/PROJECT;self.assertTrue(root.is_dir());self.assertTrue((root/'unauthorized.txt').exists());self.assertNotEqual(result['status'],'COMPLETED');record=result['delegations'][0];self.assertFalse(record['result']['verification']['verified']);self.assertIn('delegated_action_independent_verification_failed',str(record['result']['failure']))

    def test_persisted_grant_restart_executes_and_expired_or_consumed_restart_denies(self):
        with tempfile.TemporaryDirectory() as d:
            db,g,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id)
            restarted=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=restarted.load(record.request.request_id).request;result=restarted.execute(req);self.assertEqual(result.status,'COMPLETED');self.assertTrue((g.system.workspaces.root/PROJECT/'src/example.py').is_file());self.assertEqual(restarted.grants.load(grant.grant_id).state,'CONSUMED')
            restarted2=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine())
            with self.assertRaisesRegex(PermissionError,'not active'):
                restarted2.grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_scaffold',capability='workspace_scaffold',arguments=grant.scope['arguments'])
        with tempfile.TemporaryDirectory() as d:
            db,g,_,agent,first=self._start(d);aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');record=agent.delegation.load(first['delegations'][0]['request']['request_id']);grant=agent.delegation.grants.issue(record.request,agent.store.load_approval(aid));agent.delegation.attach_grant(record.request.request_id,grant.grant_id);grant.expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();grant.fingerprint=agent.delegation.grants.fingerprint(grant);agent.store.update_delegation_grant_payload(grant.grant_id,grant.to_dict());restarted=SpecialistDelegationService(Gen2Store(db),g,PolicyEngine());req=restarted.load(record.request.request_id).request
            with self.assertRaisesRegex(PermissionError,'expired'):restarted.grants.check(grant.grant_id,request=req,specialist='application_builder',tool='workspace_scaffold',capability='workspace_scaffold',arguments=grant.scope['arguments'])

    def test_second_processing_does_not_duplicate_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,agent,first=self._start(d);final=self._approve_resume(agent,first);self.assertEqual(final['status'],'COMPLETED');builds_before=len(g.system.workspaces.list(limit=100));again=agent.resume(first['goal_id']);self.assertEqual(again['status'],'COMPLETED');self.assertEqual(len(g.system.workspaces.list(limit=100)),builds_before);self.assertEqual(len(again['delegations']),1)

    def test_direct_nondelegated_calculator_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            result=PersonalAgent(Gen2Store(Path(d)/'g.db'),DirectGateway(),planner=StaticPlanner(direct_plan())).start('Calculate 700 + 3.');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['delegations'],[]);self.assertIn('703',result['text'])

if __name__=='__main__':unittest.main()
