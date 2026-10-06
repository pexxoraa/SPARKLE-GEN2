import os,tempfile,unittest
from types import SimpleNamespace
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from sparkle.system import SparkleSystem
from sparkle.secrets import SecretResolver
from sparkle_gen2.automation_orchestration import AutomationOrchestrator
from sparkle_gen2.default_acceptance import build_acceptance_matrix
from sparkle_gen2.experiments import ExperimentManager
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.iot_adapter import TypedIoTAdapter
from sparkle_gen2.multimodal import MultimodalGateway
from sparkle_gen2.proactive import ProactiveEventEngine
from sparkle_gen2.robotics import MotionSafetyEnvelope,RobotSafetyGateway
from sparkle_gen2.ros2_live import ros_environment
from sparkle_gen2.world_model import WorldModel
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.outlook_connector import OutlookCredentialSource,OutlookGraphAdapter
from sparkle_gen2.protected_secrets import protected_credential_file_refs,protected_gen2_environment,protected_voicechat_environment,protected_worker_client_config,VOICECHAT_SECRET_REF
from sparkle_gen2.required_capabilities import MASTER_REQUIRED_CAPABILITIES
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.self_improvement import ControlledImprovementPipeline

class Agent:
    gen1=None
    def start(self,prompt,*,user_id='user'):return {'goal_id':'g-auto','status':'COMPLETED','trace_id':'t','text':'ok'}
    def resume(self,goal_id):return {'goal_id':goal_id,'status':'COMPLETED','trace_id':'t','text':'ok','approvals':[]}

class MasterFinalizationTests(unittest.TestCase):
    def test_protected_gen2_environment_loads_only_explicit_allowlist_and_voice_helper_stays_narrow(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'gen2.env';p.write_text('NVIDIA_API_KEY=model-secret\nNEMOTRON_VOICECHAT_API_KEY=voice-secret\nUNRELATED_SECRET=never-load\n');p.chmod(0o600)
            env,status=protected_gen2_environment(base={},path=p);self.assertEqual(set(env),{'NVIDIA_API_KEY','NEMOTRON_VOICECHAT_API_KEY'});self.assertTrue(status['NVIDIA_API_KEY'].credential_value_loaded);self.assertNotIn('UNRELATED_SECRET',env)
            voice,vstatus=protected_voicechat_environment(base={},path=p);self.assertEqual(set(voice),{VOICECHAT_SECRET_REF});self.assertTrue(vstatus.credential_value_loaded)

    def test_protected_connector_files_require_owner_only_regular_files_and_reject_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'google').mkdir();(root/'github').mkdir();good=root/'google/gmail-token.json';good.write_text('{}');good.chmod(0o600);bad=root/'google/calendar-token.json';bad.write_text('{}');bad.chmod(0o644);target=root/'github/real.json';target.write_text('{}');target.chmod(0o600);(root/'github/github-token.json').symlink_to(target)
            refs=protected_credential_file_refs(root=root);self.assertEqual(refs.get('SPARKLE_GMAIL_TOKEN_FILE'),good.resolve());self.assertNotIn('SPARKLE_CALENDAR_TOKEN_FILE',refs);self.assertNotIn('SPARKLE_GITHUB_TOKEN_FILE',refs)

    def test_protected_worker_client_config_is_owner_only_loopback_tls_and_key_file_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);key=root/'key';ca=root/'ca.crt';key.write_text('x'*40);ca.write_text('test-ca');key.chmod(0o600);ca.chmod(0o600);cfg=root/'worker.env';cfg.write_text(f'SPARKLE_EXTERNAL_WORKER_ENABLED=true\nSPARKLE_EXTERNAL_WORKER_URL=https://127.0.0.1:8770/execute\nSPARKLE_EXTERNAL_WORKER_ID=worker-1\nSPARKLE_EXTERNAL_WORKER_SIGNING_KEY_FILE={key}\nSSL_CERT_FILE={ca}\nUNRELATED_SECRET=never-load\n');cfg.chmod(0o600);value=protected_worker_client_config(path=cfg);self.assertTrue(value['configured']);self.assertEqual(value['endpoint'],'https://127.0.0.1:8770/execute');self.assertNotIn('UNRELATED_SECRET',value)
            cfg.write_text(cfg.read_text().replace('https://127.0.0.1:8770/execute','https://example.com/execute'));self.assertFalse(protected_worker_client_config(path=cfg)['configured']);cfg.chmod(0o644);self.assertFalse(protected_worker_client_config(path=cfg)['configured'])

    def test_external_workspace_result_without_isolation_evidence_never_verifies(self):
        class Worker:
            def list(self,limit=100):return [{'external_test_run_id':7,'project_name':'project','status':'passed','returncode':0,'timed_out':False,'response_verified':True,'isolation_verified':False}]
        gateway=LocalGen1Gateway.__new__(LocalGen1Gateway);gateway._external_workspace_worker=Worker();gateway.system=SimpleNamespace(workspace_tests=SimpleNamespace(list=lambda limit=100:[]));output={'external_test_run_id':7,'project_name':'project','status':'passed','returncode':0,'timed_out':False,'response_verified':True,'isolation_verified':False};verification=gateway._verify_observation('workspace_test',{'project_name':'project','approved':True},output);self.assertFalse(verification['verified']);self.assertFalse(verification['isolation_verified'])

    def test_automation_disable_is_distinct_terminal_control_and_requires_approval_policy(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')}):
            Path(os.environ['SPARKLE_DATA_DIR']).mkdir();g=LocalGen1Gateway(SparkleSystem());store=Gen2Store(Path(d)/'g2.db');svc=AutomationOrchestrator(store,g,lambda:Agent());future=(datetime.now(UTC)+timedelta(days=1)).isoformat();aid=svc.create(owner_user_id='alice',source_goal_id='goal',name='a',trigger_type='scheduled',prompt='x',schedule_kind='daily',next_run_at=future)['automation']['id'];view=svc.disable(aid,'alice');self.assertFalse(view['automation']['enabled']);self.assertEqual(view['object']['status'],'DISABLED');self.assertEqual(AutomationOrchestrator(Gen2Store(Path(d)/'g2.db'),LocalGen1Gateway(SparkleSystem()),lambda:Agent()).inspect(aid)['object']['status'],'DISABLED')
            permission,risk=PolicyEngine().evaluate('automation_disable','alice','automation:disable','now');self.assertEqual(permission.effect.value,'REQUIRE_APPROVAL');self.assertEqual(risk.level.value,'MEDIUM')

    def test_experiment_full_lifecycle_persists_version_verification_analysis_compare_archive(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';m=ExperimentManager(Gen2Store(path));a=m.create('A','bounded method',configuration={'seed':1},dataset='d',code_version='abc');b=m.create('B','bounded method',configuration={'seed':2},dataset='d',code_version='def');m.configure(a.experiment_id,model='model-a');m.configure(b.experiment_id,model='model-b')
            with self.assertRaises(PermissionError):m.run(a.experiment_id,lambda *_:{},approved=False)
            def runner(exp,limits):return {'observations':[{'step':'done'}],'results':{'ok':True},'metrics':{'score':0.8},'verification':{'verified':True,'method':'independent reread'}}
            m.run(a.experiment_id,runner,approved=True,resource_limits={'time_seconds':30,'max_result_bytes':50000,'max_observations':5});m.run(b.experiment_id,lambda e,l:{'results':{'ok':True},'metrics':{'score':0.9},'verification':{'verified':True}},approved=True);self.assertEqual(m.items[a.experiment_id].verification_state,'VERIFIED');m.pause(a.experiment_id);m.resume(a.experiment_id);analysis=m.analyze(a.experiment_id);self.assertEqual(analysis['numeric_metrics']['score'],0.8);cmp=m.compare([a.experiment_id,b.experiment_id]);self.assertEqual(cmp['common_numeric_metrics']['score'][0]['experiment_id'],b.experiment_id);m.conclude(a.experiment_id,'supported');m.archive(a.experiment_id);recovered=ExperimentManager(Gen2Store(path)).items[a.experiment_id];self.assertEqual(recovered.status,'ARCHIVED');self.assertGreater(recovered.version,1)

    def test_experiment_failed_verification_never_becomes_success(self):
        m=ExperimentManager();e=m.create('h','m')
        with self.assertRaisesRegex(RuntimeError,'verification failed'):m.run(e.experiment_id,lambda *_:{'results':{'x':1},'verification':{'verified':False}},approved=True)
        self.assertEqual(m.items[e.experiment_id].status,'FAILED');self.assertEqual(m.items[e.experiment_id].verification_state,'FAILED')

    def test_multimodal_normalization_is_bytes_only_bounded_and_mime_checked(self):
        from test_master_multimodal_personal_core import PNG,WAV
        g=MultimodalGateway();png=PNG;item=g.normalize_bytes(png,mime_type='image/png',media_id='img1');self.assertEqual(item.modality,'image');self.assertEqual(item.location,'memory://img1');self.assertEqual(len(item.sha256),64);self.assertTrue(item.metadata['metadata_stripped'])
        with self.assertRaises(ValueError):g.normalize_bytes(png,modality='audio',mime_type='image/png')
        with self.assertRaises(TypeError):g.normalize_bytes('/tmp/image.png',mime_type='image/png')
        wav=WAV;audio=g.normalize_bytes(wav,mime_type='audio/wav');self.assertEqual(audio.modality,'audio')

    def test_proactive_events_deduplicate_replay_and_preserve_correlation_priority(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');engine=ProactiveEventEngine(store);a=engine.ingest('important_email','bounded subject',{'kind':'mail'},.9,correlation_id='corr-1',priority='HIGH');b=engine.ingest('important_email','bounded subject',{'kind':'mail'},.9,correlation_id='corr-1',priority='HIGH');self.assertEqual(a.event_id,b.event_id);self.assertEqual(a.fingerprint,b.fingerprint);self.assertEqual(a.priority,'HIGH');self.assertEqual(len(store.proactive_events()),1);ready=engine.evaluate(a.event_id);self.assertEqual(ready.status,'READY');self.assertEqual(ready.action,'NOTIFY')

    def test_world_model_distinguishes_observed_inferred_predicted_and_confidence(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';w=WorldModel(Gen2Store(db));o=w.observe('device','device',{'online':True},{'source':'device'},confidence=.99);i=w.infer('risk','event',{'level':'medium'},{'source':'analysis'},confidence=.6);p=w.predict('deadline','event',{'days':2},{'source':'forecast'},confidence=.4);self.assertEqual(o.epistemic_state,'observed');self.assertEqual(i.epistemic_state,'inferred');self.assertEqual(p.epistemic_state,'predicted');self.assertAlmostEqual(i.confidence,.6);r=WorldModel(Gen2Store(db));self.assertEqual(r.nodes['risk'].epistemic_state,'inferred');self.assertEqual(r.nodes['deadline'].epistemic_state,'predicted')

    def test_ros_environment_is_fixed_shell_free_and_does_not_inherit_secrets(self):
        with patch.dict(os.environ,{'AWS_SECRET_ACCESS_KEY':'must-not-inherit','ROS_DOMAIN_ID':'7','RMW_IMPLEMENTATION':'rmw_fastrtps_cpp'},clear=False):
            env=ros_environment();self.assertEqual(env['ROS_DOMAIN_ID'],'7');self.assertEqual(env['RMW_IMPLEMENTATION'],'rmw_fastrtps_cpp');self.assertNotIn('AWS_SECRET_ACCESS_KEY',env);self.assertTrue(env['PATH'].startswith('/opt/ros/lyrical/bin:'));self.assertNotIn('/bin/bash',str(env))

    def test_motion_safety_rejects_unsafe_commands_before_adapter(self):
        calls=[];clock=[10.0];state={'pose':{'x':0.0,'y':0.0,'theta':0.0},'timestamp':datetime.now(UTC).isoformat()};safe=MotionSafetyEnvelope(max_velocity=.2,max_displacement=.3,max_angle=.4,max_command_rate_hz=2,stale_after_seconds=2,workspace=(-1,1,-1,1));g=RobotSafetyGateway(lambda a,p:(calls.append((a,p)) or {'ok':True}),lambda:False,lambda a,r:{'verified':True},safety=safe,state_reader=lambda:dict(state),clock=lambda:clock[0])
        with self.assertRaises(PermissionError):g.command('move',{'distance':.4,'velocity':.1},approved=True)
        with self.assertRaises(PermissionError):g.command('move',{'distance':.1,'velocity':.3},approved=True)
        with self.assertRaises(PermissionError):g.command('move',{'distance':float('nan')},approved=True)
        self.assertEqual(calls,[]);self.assertTrue(g.execute_verified('move',{'distance':.1,'velocity':.1},approved=True)['verification']['verified']);self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(PermissionError,'rate'):g.command('move',{'distance':.1,'velocity':.1},approved=True)
        clock[0]+=1;state['pose']['x']=.95
        with self.assertRaisesRegex(PermissionError,'workspace'):g.command('move',{'distance':.2,'velocity':.1},approved=True)
        state['timestamp']='2000-01-01T00:00:00+00:00';clock[0]+=1
        with self.assertRaisesRegex(RuntimeError,'stale'):g.command('move',{'distance':.1,'velocity':.1},approved=True)

    def test_motion_safety_estop_approval_and_verification_remain_authoritative(self):
        active=[True];g=RobotSafetyGateway(lambda a,p:{'ok':True},lambda:active[0],lambda a,r:{'verified':False})
        with self.assertRaisesRegex(RuntimeError,'emergency_stop'):g.command('move',{'distance':.1},approved=True)
        active[0]=False
        with self.assertRaises(PermissionError):g.command('move',{'distance':.1},approved=False)
        with self.assertRaisesRegex(RuntimeError,'verification_failed'):g.execute_verified('move',{'distance':.1},approved=True)

    def test_typed_iot_and_esp32_boundaries_are_device_scoped_verified_and_deny_raw_gpio(self):
        class T:
            def __init__(self):self.state={'relay':'off'}
            def health(self):return {'ok':True}
            def read_state(self,p):return dict(self.state)
            def control(self,p):self.state[p['action']]=p['value'];return {'accepted':True,'request_reference':'r1'}
            def verify(self,result):return {'verified':self.state.get(result.get('action'))=='on','method':'state reread'}
        dev={'device_id':'esp-safe','kind':'esp32','status':'ONLINE','capabilities':['relay'],'safety_limits':{'relay':{'allowed_values':['on','off']}}}
        a=TypedIoTAdapter(dev,T(),owner_user_id='u',scope_prefix='esp32');self.assertTrue(a.configured());self.assertEqual(a.authorize()['granted_scopes'],['esp32.read','esp32.act']);read=a.invoke_with_context('read',{},owner_user_id='u',device_id='esp-safe');self.assertTrue(a.verify_with_context('read',read,owner_user_id='u')['verified'])
        with self.assertRaises(PermissionError):a.invoke_with_context('act',{'action':'raw_gpio','value':1},owner_user_id='u',device_id='esp-safe')
        with self.assertRaises(PermissionError):a.invoke_with_context('act',{'action':'relay','value':'invalid'},owner_user_id='u',device_id='esp-safe')
        out=a.invoke_with_context('act',{'action':'relay','value':'on'},owner_user_id='u',device_id='esp-safe');self.assertTrue(a.verify_with_context('act',out,owner_user_id='u')['verified'])

    def test_outlook_graph_software_boundary_read_draft_send_and_reread(self):
        class R:
            def __init__(self,value,status=200):self.value=value;self.status=status
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self):return b'' if self.value is None else __import__('json').dumps(self.value).encode()
        draft={'id':'m1','conversationId':'c1','subject':'Test','receivedDateTime':'2026-01-01T00:00:00Z','isRead':False,'isDraft':True}
        sent=dict(draft,isDraft=False)
        state={'sent':False}
        def opener(req,timeout):
            u=req.full_url;method=req.get_method()
            if u.endswith('/me?%24select=id') or '/me?' in u:return R({'id':'account1'})
            if '/me/messages?' in u:return R({'value':[draft]})
            if u.endswith('/me/messages') and method=='POST':return R(draft)
            if '/me/messages/m1/send' in u and method=='POST':state['sent']=True;return R(None,202)
            if '/me/messages/m1?' in u:return R(sent if state['sent'] else draft)
            raise AssertionError((method,u))
        a=OutlookGraphAdapter(OutlookCredentialSource(SecretResolver({'MICROSOFT_GRAPH_TOKEN':'test-only'})),opener=opener);self.assertTrue(a.health()['ok']);read=a.invoke('read',{'max_results':1});self.assertTrue(a.verify('read',read)['verified']);drafted=a.invoke('draft',{'subject':'Test','body':'bounded','to':['user@example.test']});self.assertTrue(a.verify('draft',drafted)['verified']);sent_result=a.invoke('send',{'message_id':'m1'});self.assertTrue(a.verify('send',sent_result)['verified']);self.assertNotIn('test-only',str(read)+str(drafted)+str(sent_result))

    def test_self_improvement_requires_security_review_and_verified_human_rollback(self):
        installer=lambda c:{'registered':True,'rollback_available':True,'rollback_strategy':'restore_previous','rollback_reference':'safe-ref'};p=ControlledImprovementPipeline(installer=installer);c=p.propose('context','bounded change');p.implement(c.candidate_id,{'artifact':'candidate'});p.record_tests(c.candidate_id,True);p.review(c.candidate_id,True)
        with self.assertRaises(ValueError):p.approve(c.candidate_id,'human')
        p.record_security(c.candidate_id,True,{'verified':True,'checks':['policy','secrets']});p.approve(c.candidate_id,'human');installed=p.install(c.candidate_id);self.assertTrue(installed['rollback']['available'])
        with self.assertRaises(PermissionError):p.rollback_install(c.candidate_id,lambda r:{'verified':True},actor='model')
        rolled=p.rollback_install(c.candidate_id,lambda r:{'verified':r['strategy']=='restore_previous'},actor='human');self.assertEqual(rolled['candidate'].status,'ROLLED_BACK')
        with self.assertRaises(PermissionError):p.propose('approval_bypass','unsafe')

    def test_acceptance_matrix_covers_master_and_reconciled_live_capabilities(self):
        m=build_acceptance_matrix();self.assertEqual(set(m.items),MASTER_REQUIRED_CAPABILITIES);self.assertEqual(m.unresolved(),[])
        for name in ('gmail','calendar','drive','github_connector','image_generation','browser_control','linux_application_control','gui_computer_control','workspace_test_execution','voice_stt_tts'):self.assertEqual(m.items[name].status,'LIVE_VERIFIED')
        for name in ('mobile','mqtt','esp32','ros2_robotics','outlook','source_control_push'):self.assertEqual(m.items[name].status,'EXTERNALLY_BLOCKED')

if __name__=='__main__':unittest.main()
