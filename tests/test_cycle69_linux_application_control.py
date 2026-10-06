import json,os,subprocess,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from sparkle.secrets import SecretResolver
from sparkle_gen2.connector_catalog import DESCRIPTORS
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.linux_application import LinuxApplicationAdapter,LinuxApplicationError,LinuxCommand,MAX_OUTPUT_BYTES,MAX_OUTPUT_LINES
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import ApprovalStatus,PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class Approval:
    def __init__(self,goal='g',task='t'):self.status=ApprovalStatus.APPROVED;self.goal_id=goal;self.task_run_id=task;self.approval_id='approval-linux'
class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        p,r=super().evaluate(capability,subject,scope,timestamp)
        if capability=='linux.inspect':p.effect=PermissionEffect.DENY
        return p,r
class CP:
    def __init__(self,stdout=b'',stderr=b'',returncode=0):self.stdout=stdout;self.stderr=stderr;self.returncode=returncode

class Cycle69LinuxApplicationControlTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='linux')
    def manager(self,store=None,*,owner='alice',root=None,policy=None,adapter=None):
        a=adapter or LinuxApplicationAdapter(owner_user_id=owner,allowed_roots=[root] if root else None);auth=a.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=a);m.authorize('linux',['linux.inspect','linux.execute'],owner_user_id=owner,actor='local-test',reference=auth['authorization_reference']);m.connect('linux',owner_user_id=owner);return m,a

    def test_exact_descriptor_modes_and_no_shell_capability(self):
        d=self.descriptor();self.assertTrue(d.device_scoped);self.assertEqual(d.provider_system,'SPARKLE bounded Linux application boundary');caps={x.operation:x for x in d.capabilities};self.assertEqual(set(caps),{'inspect','execute'});self.assertEqual(caps['inspect'].mode.value,'READ');self.assertEqual(caps['inspect'].policy_capability,'linux.inspect');self.assertEqual(caps['execute'].mode.value,'CONTROL');self.assertEqual(caps['execute'].policy_capability,'linux.execute');self.assertNotIn('shell',{x.operation for x in d.capabilities})

    def test_no_shell_true_or_shell_interpreter_execution_in_adapter(self):
        src=Path('src/sparkle_gen2/linux_application.py').read_text();self.assertNotIn('shell=True',src);self.assertNotIn("'/bin/bash'",src);self.assertNotIn("'/bin/sh'",src);self.assertNotIn('bash -c',src);self.assertNotIn('sh -c',src)

    def test_inspect_real_allowlist_and_verification(self):
        m,a=self.manager()
        for kind in ('cwd','os','identity','disk','memory','list_directory'):
            with self.subTest(kind=kind):
                r=m.invoke_read('linux','inspect',{'kind':kind},'linux.inspect',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertTrue(r['verification']['verified']);self.assertEqual(r['result']['operation'],'inspect')

    def test_arbitrary_shell_sudo_unknown_and_executable_payload_fail_closed(self):
        m,_=self.manager()
        for payload in ({'kind':'arbitrary_shell'},{'kind':'shell'},{'kind':'sudo'}):
            with self.subTest(payload=payload),self.assertRaises(PermissionError):m.invoke_read('linux','inspect',payload,'linux.inspect',owner_user_id='alice')
        for payload in ({'action':'sudo'},{'action':'raw_command'},{'action':'launch','executable':'/bin/ls'},{'action':'launch_sleep_probe','command':'id'}):
            with self.subTest(payload=payload),self.assertRaises((PermissionError,ValueError)):m.invoke('linux','execute',payload,'linux.execute',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())

    def test_command_argument_count_size_timeout_and_metacharacters(self):
        a=LinuxApplicationAdapter(owner_user_id='alice');exe=a._resolve_executable(a._FIXED_COMMANDS['os'][0]);allowed=a._allowed_execs()
        for cmd in (LinuxCommand(exe,tuple('x' for _ in range(9))),LinuxCommand(exe,('x'*257,)),LinuxCommand(exe,('x;id',)),LinuxCommand(exe,('$(id)',)),LinuxCommand(exe,(),timeout_seconds=11)):
            with self.subTest(cmd=cmd),self.assertRaises(ValueError):a._validate_command(cmd,allowed)
        with self.assertRaises(PermissionError):a._validate_command(LinuxCommand('/usr/bin/python3',()),allowed)

    def test_timeout_and_output_bounds(self):
        def timeout_runner(*a,**k):raise subprocess.TimeoutExpired(a[0],1)
        a=LinuxApplicationAdapter(owner_user_id='alice',runner=timeout_runner);cmd=a._command('os',working_directory=str(a.allowed_roots[0]),timeout_seconds=1)
        with self.assertRaises(LinuxApplicationError) as cm:a._run(cmd)
        self.assertEqual(cm.exception.category,'TIMEOUT')
        huge=(b'x\n'*(MAX_OUTPUT_LINES+50))+b'y'*(MAX_OUTPUT_BYTES+200)
        a=LinuxApplicationAdapter(owner_user_id='alice',runner=lambda *a,**k:CP(huge,b''));out,err,tr=a._run(a._command('os',working_directory=str(a.allowed_roots[0])));self.assertTrue(tr);self.assertLessEqual(len(out.encode()),MAX_OUTPUT_BYTES);self.assertLessEqual(len(out.splitlines()),MAX_OUTPUT_LINES)

    def test_filesystem_root_traversal_symlink_sensitive_absolute_denial(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as outside:
            root=Path(d);(root/'safe').mkdir();(root/'safe'/'a.txt').write_text('ok');(root/'.ssh').mkdir();(root/'.ssh'/'id_test').write_text('secret');(root/'escape').symlink_to(Path(outside),target_is_directory=True);m,a=self.manager(root=root)
            r=m.invoke_read('linux','inspect',{'kind':'list_directory','path':'safe'},'linux.inspect',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED')
            root_listing=m.invoke_read('linux','inspect',{'kind':'list_directory'},'linux.inspect',owner_user_id='alice');self.assertNotIn('.ssh',[x['name'] for x in root_listing['result']['result']['data']['entries']])
            for path in ('../','%2e%2e/etc','/etc','escape','.ssh'):
                with self.subTest(path=path),self.assertRaises(PermissionError):m.invoke_read('linux','inspect',{'kind':'list_directory','path':path},'linux.inspect',owner_user_id='alice')

    def test_environment_is_sanitized(self):
        seen={}
        def runner(argv,**kwargs):seen.update(kwargs);return CP(b'Linux 1 x86_64',b'')
        a=LinuxApplicationAdapter(owner_user_id='alice',runner=runner);a._run(a._command('os',working_directory=str(a.allowed_roots[0])));self.assertEqual(seen['env'],{'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'});self.assertNotIn('HOME',seen['env']);self.assertNotIn('AWS_SECRET_ACCESS_KEY',seen['env'])

    def test_owner_and_device_isolation_and_trusted_auto_binding(self):
        m,a=self.manager();r=m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED')
        with self.assertRaises(PermissionError):m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='alice',device_id='linux-device:wrong')
        with self.assertRaises(PermissionError):m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='bob')

    def test_policy_allow_deny_execute_requires_approval_model_cannot_self_approve(self):
        p,r=PolicyEngine().evaluate('linux.inspect','alice','linux:inspect',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');p2,_=PolicyEngine().evaluate('linux.execute','alice','linux:execute',now());self.assertEqual(p2.effect,PermissionEffect.REQUIRE_APPROVAL)
        m,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='alice')
        m,_=self.manager()
        with self.assertRaises(PermissionError):m.invoke('linux','execute',{'action':'launch_sleep_probe'},'linux.execute',owner_user_id='alice',goal_id='g',task_run_id='t')
        with self.assertRaises(PermissionError):m.invoke('linux','execute',{'action':'launch_sleep_probe','approved':True},'linux.execute',owner_user_id='alice',goal_id='g',task_run_id='t')

    def test_control_postcondition_verified_and_cleanup(self):
        m,a=self.manager();r=m.invoke('linux','execute',{'action':'launch_sleep_probe','duration_seconds':3},'linux.execute',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(r['status'],'VERIFIED');self.assertTrue(r['verification']['verified']);self.assertTrue(r['verification']['command_digest']);self.assertTrue(r['verification']['executable_identity']);self.assertIsNone(a._active)

    def test_failed_control_verification_not_verified(self):
        class Dead:
            pid=999999
            def poll(self):return 0
            def terminate(self):pass
            def wait(self,timeout=None):return 0
        a=LinuxApplicationAdapter(owner_user_id='alice');a._active=Dead();result={'provider':a.provider,'operation':'execute','result':{'action':'launch_sleep_probe','application':'sleep_probe','process_reference':'x','started':True,'command_digest':'a'*64}};v=a.verify_with_context('execute',result,owner_user_id='alice');self.assertFalse(v['verified'])

    def test_persistence_digest_no_output_or_secret_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g2.sqlite3';store=Gen2Store(db);m,a=self.manager(store);r=m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');row=m.invocations(owner_user_id='alice',connector_id='linux')[0];self.assertEqual(row['verification_status'],'VERIFIED');self.assertTrue(row['arguments_digest']);raw=db.read_bytes();self.assertNotIn(str(r['result']['result']['data']).encode(),raw);self.assertNotIn(b'AWS_SECRET_ACCESS_KEY',raw)
            a2=LinuxApplicationAdapter(owner_user_id='alice');m2=ConnectorManager(Gen2Store(db),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=a2);self.assertEqual(m2.health('linux',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='linux')),1);self.assertIsNone(a2._active)

    def test_revoke_closes_and_prevents_further_execution(self):
        m,a=self.manager();m.revoke('linux',owner_user_id='alice',actor='human');self.assertTrue(a._closed);self.assertEqual(m.health('linux',owner_user_id='alice')['status'],'REVOKED')
        with self.assertRaises(PermissionError):m.invoke_read('linux','inspect',{'kind':'os'},'linux.inspect',owner_user_id='alice')

    def test_personalagent_read_and_control_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,a=self.manager(store,owner='user');g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}))
            p=PlanProposal(uuid.uuid4().hex,'linux',[PlanProposalStep('r','Inspect OS',['connector_read'],[],['verified'],{'connector_id':'linux','operation':'inspect','arguments':{'kind':'os'},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(p),connector_manager=m);res=agent.start('What operating system am I running?',user_id='user');self.assertEqual(res['status'],'COMPLETED');self.assertEqual(res['approvals'],[])
            p2=PlanProposal(uuid.uuid4().hex,'linux',[PlanProposalStep('x','Launch approved probe',['connector_invoke'],[],['verified'],{'connector_id':'linux','operation':'execute','arguments':{'action':'launch_sleep_probe','duration_seconds':3},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());agent2=PersonalAgent(store,g,planner=StaticPlanner(p2),connector_manager=m);first=agent2.start('Launch the approved program.',user_id='user');self.assertEqual(first['status'],'WAITING');agent2.decide_approval(first['approvals'][0],'approve',actor='human');done=agent2.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED')

    def test_previous_connectors_and_model_routes_unchanged(self):
        desc={x.connector_id:{c.operation for c in x.capabilities} for x in DESCRIPTORS};self.assertEqual(desc['gmail'],{'list_messages','get_message_metadata'});self.assertEqual(desc['calendar'],{'list_calendars','list_events','get_event'});self.assertEqual(desc['drive'],{'list_files','get_file_metadata'});self.assertEqual(desc['github'],{'get_user','list_repositories','get_repository','list_repository_contents','list_issues','list_pull_requests','list_workflows'});self.assertEqual(desc['browser'],{'navigate','read','interact'})
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));mm=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(mm.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
