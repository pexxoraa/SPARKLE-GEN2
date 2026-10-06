import tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace

from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.workspace_isolation import PROFILE,StrictBubblewrapExecutor,StrictLocalWorkspaceWorker
from sparkle.worker_executor import ExecutorResult

class FakeGateway:
    def __init__(self):self.calls=[]
    def health(self):
        return {'available':True,'tools':['workspace_test'],'tool_definitions':[{'name':'workspace_test','description':'bounded','parameters':{'type':'object','properties':{'project_name':{'type':'string'}},'required':['project_name'],'additionalProperties':False}}]}
    def retrieve_context(self,*a,**k):return {'source':'test','rendered':''}
    def invoke(self,tool,args):
        self.calls.append((tool,dict(args)))
        ok=tool=='workspace_test' and set(args)=={'project_name','approved'} and args['approved'] is True
        return ToolObservation(ok,tool,{'project_name':args.get('project_name'),'status':'passed','external_test_run_id':1,'response_verified':True,'isolation_verified':True},{'verified':ok,'isolation_verified':ok,'filesystem_isolation':ok,'network_isolation':ok})

def proposal(arguments):
    return PlanProposal(uuid.uuid4().hex,'workspace-test',[PlanProposalStep('test','Run bounded isolated workspace tests',['workspace_test'],[],['signed isolation and test result verified'],dict(arguments),30,0)],[{'description':'workspace tests independently verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],now())

class WorkspaceTestIsolationBoundaryTests(unittest.TestCase):
    def agent(self,d,args):
        store=Gen2Store(Path(d)/'g.db');gateway=FakeGateway();agent=PersonalAgent(store,gateway,planner=StaticPlanner(proposal(args)),max_replans=0);return store,gateway,agent
    def test_workspace_test_requires_human_approval_and_injects_transport_flag_only_after_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,agent=self.agent(d,{'project_name':'safeproject'});first=agent.start('Run the isolated tests.',user_id='alice');self.assertEqual(first['status'],'WAITING');self.assertEqual(g.calls,[])
            aid=first['approvals'][0];agent.decide_approval(aid,'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(g.calls,[('workspace_test',{'project_name':'safeproject','approved':True})])
            grants=[p for p in store.permissions_for_goal(first['goal_id']) if p.capability=='workspace_test' and p.metadata.get('one_time')];self.assertEqual(len(grants),1);self.assertEqual(grants[0].status.value,'REVOKED');self.assertEqual(grants[0].metadata.get('revoked_by'),'workspace_test_consumer')
    def test_model_authority_fields_are_rejected_before_approval_or_execution(self):
        for field,value in [('approved',True),('approval_id','fake'),('grant_id','fake'),('authorization_override',True)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                _,g,agent=self.agent(d,{'project_name':'safeproject',field:value});result=agent.start('Run tests.',user_id='alice');self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['approvals'],[]);self.assertEqual(g.calls,[])
    def test_post_approval_scope_mutation_is_denied(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,agent=self.agent(d,{'project_name':'safeproject'});first=agent.start('Run tests.',user_id='alice');plan=store.load_plan(store.load_goal(first['goal_id']).plan_id);plan.steps[0].arguments['project_name']='otherproject';store.save_plan(plan);agent.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'BLOCKED');self.assertEqual(g.calls,[])
    def test_model_actor_cannot_turn_approval_into_execution_grant(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,agent=self.agent(d,{'project_name':'safeproject'});first=agent.start('Run tests.',user_id='alice');aid=first['approvals'][0]
            with self.assertRaisesRegex(PermissionError,'model_cannot_approve'):agent.decide_approval(aid,'approve',actor='model')
            self.assertEqual(store.load_approval(aid).status.value,'PENDING');self.assertEqual(g.calls,[])

class StrictWorkerContractTests(unittest.TestCase):
    def test_model_visible_schema_hides_transport_approval_field(self):
        from sparkle.system import SparkleSystem
        from sparkle_gen2.gen1 import LocalGen1Gateway
        gateway=LocalGen1Gateway(SparkleSystem())
        definition=next(x for x in gateway.health()['tool_definitions'] if x['name']=='workspace_test')
        self.assertEqual(set(definition['parameters']['properties']),{'project_name'})
        self.assertEqual(definition['parameters']['required'],['project_name'])
        self.assertFalse(definition['parameters']['additionalProperties'])
        if gateway._strict_workspace_worker:gateway._strict_workspace_worker.close()

    def test_strict_worker_preserves_source_bundle_resource_ceilings(self):
        with tempfile.TemporaryDirectory() as d:
            worker=StrictLocalWorkspaceWorker(Path(d))
            self.assertEqual(worker._bundler.MAX_FILES,500)
            self.assertEqual(worker._bundler.MAX_TOTAL_BYTES,5_000_000)
            self.assertEqual(worker._bundler.MAX_FILE_BYTES,500_000)
            worker.close()

    def test_strict_mount_profile_has_readonly_root_one_writable_workspace_and_no_shell(self):
        with tempfile.TemporaryDirectory() as d:
            command=StrictBubblewrapExecutor()._base_command(Path(d))
            self.assertIn('--remount-ro',command);self.assertEqual(command.count('--bind'),1);self.assertNotIn('--tmpfs',command);self.assertNotIn('/bin/sh',command);self.assertNotIn('/bin/bash',command);self.assertEqual(PROFILE,'SPARKLE-GEN2-WORKSPACE-STRICT/1')
    def test_operator_boundary_rejects_symlink_and_rotates_worker_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'target';(target/'tests').mkdir(parents=True);(target/'tests/test_ok.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n');link=root/'link';link.symlink_to(target, target_is_directory=True)
            first=StrictLocalWorkspaceWorker(root);second=StrictLocalWorkspaceWorker(root);self.assertNotEqual(first.worker_id,second.worker_id);self.assertTrue(first.worker_id.startswith('sparkle-gen2-strict-'))
            with self.assertRaisesRegex(ValueError,'unsafe'):first.run_directory('symlinkprobe',link,approved=True)
    def test_output_limit_cannot_be_reported_as_success(self):
        class FakeExecutor:
            def status(self):
                names=('host_filesystem_read','host_filesystem_write','workspace_escape','secret_environment','prohibited_network','host_process_access','artifact_modification')
                return {'available':True,'preflight_passed':True,'hostile_canaries_passed':True,'isolation_profile':PROFILE,'filesystem_isolation':True,'network_isolation':True,'ephemeral_workspace':True,'resource_limits':True,'unsafe_process_mode':False,'preflight_canary_evidence_complete':True,'canaries':{x:True for x in names},'mode':'bubblewrap'}
            def execute(self,job,*,worker_id):return ExecutorResult('passed',0,False,'x'*100,1.0,{'worker_id':worker_id,'filesystem_isolation':True,'network_isolation':True,'ephemeral':True,'resource_limits':True},True)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);work=root/'work';(work/'tests').mkdir(parents=True);(work/'tests/test_ok.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n');worker=StrictLocalWorkspaceWorker(root);worker.executor=FakeExecutor();row=worker.run_directory('limitprobe',work,approved=True,max_output_chars=100);self.assertEqual(row['status'],'failed');self.assertTrue(row['output_limited'])

if __name__=='__main__':unittest.main()
