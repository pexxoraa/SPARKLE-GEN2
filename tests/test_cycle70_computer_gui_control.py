import json,math,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from sparkle.secrets import SecretResolver
from sparkle_gen2.computer_adapter import ComputerAdapter,ComputerAdapterError,MAX_GUI_ACTIONS
from sparkle_gen2.connector_catalog import DESCRIPTORS
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import ApprovalStatus,PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class FakeComputerAdapter(ComputerAdapter):
    def __init__(self,*,owner_user_id='alice',deny=False):
        super().__init__(owner_user_id=owner_user_id,device_id='computer-device:test');self.active=False;self.deny=deny;self.keys=set();self.calls=[];self.counter=0
    def _runtime_available(self):return True
    def _call(self,cmd,args=None,timeout=25):
        self.calls.append((cmd,dict(args or {})));self.counter+=1
        if cmd=='discover':return {'remote_desktop_version':2,'remote_device_types':7,'screencast_version':5,'screen_source_types':7,'screenshot_version':2,'session_active':self.active,'selected_devices':3 if self.active else 0,'stream_count':1 if self.active else 0,'pressed_keys':sorted(self.keys)}
        if cmd=='status':return {'remote_desktop_version':2,'remote_device_types':7,'screencast_version':5,'screen_source_types':7,'screenshot_version':2,'session_active':self.active,'session_handle_present':self.active,'selected_devices':3 if self.active else 0,'stream_count':1 if self.active else 0,'pressed_keys':sorted(self.keys)}
        if cmd=='create_session':
            if self.deny:raise ComputerAdapterError('AUTH_DENIED','portal_request_denied')
            self.active=True;return {'session_handle_present':True,'selected_devices':3,'stream_count':1}
        if cmd in {'observe','screenshot'}:
            if cmd=='observe' and not self.active:raise ComputerAdapterError('AUTH_REQUIRED','session_authorization_required')
            return {'source':'screencast-pipewire' if cmd=='observe' else 'screenshot-portal','sha256':('%064x'%self.counter)[-64:],'size_bytes':4096,'width':1280,'height':720,'captured_at_ns':self.counter}
        if cmd=='pointer_move':return {'action':cmd,'accepted':True}|dict(args or {})
        if cmd=='pointer_click':return {'action':cmd,'accepted':True,'button':'left'}
        if cmd=='pointer_scroll':return {'action':cmd,'accepted':True}|dict(args or {})
        if cmd=='key_press':
            key=args['key']
            if key in self.keys:raise ComputerAdapterError('KEY_STATE','key_already_pressed')
            self.keys.add(key);return {'action':cmd,'accepted':True,'key':key,'pressed_keys':sorted(self.keys)}
        if cmd=='key_release':
            key=args['key']
            if key not in self.keys:raise ComputerAdapterError('KEY_STATE','key_not_pressed')
            self.keys.remove(key);return {'action':cmd,'accepted':True,'key':key,'pressed_keys':sorted(self.keys)}
        if cmd=='close':self.active=False;self.keys.clear();return {'status':'closed'}
        raise AssertionError(cmd)
    def close(self):
        if not self._closed:
            try:self._call('close')
            except Exception:pass
        self._session_ref=None;self._last_observation=None;self._pressed.clear();self._closed=True;return {'status':'closed','device_reference':'test'}

class Approval:
    def __init__(self,goal='g',task='t'):self.status=ApprovalStatus.APPROVED;self.goal_id=goal;self.task_run_id=task;self.approval_id='approval-c70'
class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        p,r=super().evaluate(capability,subject,scope,timestamp)
        if capability=='computer.read':p.effect=PermissionEffect.DENY
        return p,r

class Cycle70ComputerTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='computer')
    def manager(self,store=None,*,owner='alice',adapter=None,policy=None):
        a=adapter or FakeComputerAdapter(owner_user_id=owner);auth=a.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=a);m.authorize('computer',['computer.read','computer.act'],owner_user_id=owner,actor='portal-test',reference=auth['authorization_reference']);m.connect('computer',owner_user_id=owner);return m,a
    def start_session(self,m,a,owner='alice'):
        r=m.invoke_read('computer','read',{'action':'observe','authorize_session':True},'computer.read',owner_user_id=owner);self.assertEqual(r['status'],'VERIFIED');return r['result']['result']['session_reference']

    def test_descriptor_and_policy_classification(self):
        d=self.descriptor();caps={x.operation:x for x in d.capabilities};self.assertTrue(d.device_scoped);self.assertEqual(set(caps),{'read','act'});self.assertEqual(caps['read'].mode.value,'READ');self.assertEqual(caps['read'].policy_capability,'computer.read');self.assertEqual(caps['act'].mode.value,'CONTROL');self.assertEqual(caps['act'].policy_capability,'computer.act');p,r=PolicyEngine().evaluate('computer.read','u','computer:read',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');p2,_=PolicyEngine().evaluate('computer.act','u','computer:act',now());self.assertEqual(p2.effect,PermissionEffect.REQUIRE_APPROVAL)

    def test_portal_discovery_versions_devices_sources(self):
        m,a=self.manager();r=m.invoke_read('computer','read',{'action':'status'},'computer.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');p=r['result']['result']['portal'];self.assertEqual(p['remote_desktop_version'],2);self.assertEqual(p['remote_device_types'],7);self.assertEqual(p['screencast_version'],5);self.assertEqual(p['screen_source_types'],7);self.assertEqual(p['screenshot_version'],2);self.assertEqual(r['result']['result']['session_authorization'],'REQUIRED')

    def test_authorization_denial_and_explicit_success(self):
        m,a=self.manager(adapter=FakeComputerAdapter(deny=True));
        with self.assertRaises(ComputerAdapterError) as cm:m.invoke_read('computer','read',{'action':'observe','authorize_session':True},'computer.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'AUTH_DENIED')
        m,a=self.manager();sid=self.start_session(m,a);self.assertTrue(sid.startswith('computer-session:'));self.assertTrue(a.active)

    def test_screenshot_and_observe_fresh_verification(self):
        m,a=self.manager();s=m.invoke_read('computer','read',{'action':'screenshot'},'computer.read',owner_user_id='alice');self.assertEqual(s['status'],'VERIFIED');self.assertEqual(s['result']['result']['observation']['image']['source'],'screenshot-portal');sid=self.start_session(m,a);o=m.invoke_read('computer','read',{'action':'observe','session_id':sid},'computer.read',owner_user_id='alice');self.assertEqual(o['status'],'VERIFIED');self.assertTrue(o['result']['result']['observation']['stream_verified']);self.assertTrue(o['verification']['fresh_observation_sha256'])

    def test_pointer_bounds_nan_infinity_negative_and_outside(self):
        m,a=self.manager();sid=self.start_session(m,a)
        bad=[(-1,0),(0,-1),(1280,0),(0,720),(math.nan,2),(math.inf,2)]
        for x,y in bad:
            with self.subTest(x=x,y=y),self.assertRaises(ValueError):m.invoke('computer','act',{'action':'pointer_move','session_id':sid,'x':x,'y':y},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())
        r=m.invoke('computer','act',{'action':'pointer_move','session_id':sid,'x':100,'y':100},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(r['status'],'VERIFIED')

    def test_keyboard_balance_duplicate_release_and_close_pressed(self):
        m,a=self.manager();sid=self.start_session(m,a);r=m.invoke('computer','act',{'action':'key_press','session_id':sid,'key':'Escape'},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(r['status'],'VERIFIED');self.assertIn('Escape',a._pressed);r2=m.invoke('computer','act',{'action':'key_release','session_id':sid,'key':'Escape'},'computer.act',owner_user_id='alice',goal_id='g2',task_run_id='t2',approval=Approval('g2','t2'));self.assertEqual(r2['status'],'VERIFIED')
        with self.assertRaises(ComputerAdapterError):m.invoke('computer','act',{'action':'key_release','session_id':sid,'key':'Escape'},'computer.act',owner_user_id='alice',goal_id='g3',task_run_id='t3',approval=Approval('g3','t3'))
        m.invoke('computer','act',{'action':'key_press','session_id':sid,'key':'Tab'},'computer.act',owner_user_id='alice',goal_id='g4',task_run_id='t4',approval=Approval('g4','t4'));m.revoke('computer',owner_user_id='alice',actor='human');self.assertTrue(a._closed);self.assertFalse(a.keys)

    def test_bounded_action_count_and_allowlist(self):
        m,a=self.manager();sid=self.start_session(m,a)
        for i in range(MAX_GUI_ACTIONS):
            r=m.invoke('computer','act',{'action':'pointer_move','session_id':sid,'x':10+i,'y':10},'computer.act',owner_user_id='alice',goal_id=f'g{i}',task_run_id=f't{i}',approval=Approval(f'g{i}',f't{i}'));self.assertEqual(r['status'],'VERIFIED')
        with self.assertRaises(ComputerAdapterError):m.invoke('computer','act',{'action':'pointer_move','session_id':sid,'x':20,'y':20},'computer.act',owner_user_id='alice',goal_id='gx',task_run_id='tx',approval=Approval('gx','tx'))
        for action in ('type_text','clipboard','drag','launch','shell','delete','purchase'):
            with self.subTest(action=action),self.assertRaises(PermissionError):m.invoke('computer','act',{'action':action,'session_id':sid},'computer.act',owner_user_id='alice',goal_id='z',task_run_id='z',approval=Approval('z','z'))

    def test_stale_session_owner_device_isolation(self):
        m,a=self.manager();sid=self.start_session(m,a)
        with self.assertRaises(ComputerAdapterError):m.invoke('computer','act',{'action':'pointer_click','session_id':'computer-session:stale'},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())
        with self.assertRaises(PermissionError):m.invoke_read('computer','read',{'action':'status'},'computer.read',owner_user_id='alice',device_id='computer-device:wrong')
        with self.assertRaises(PermissionError):m.invoke_read('computer','read',{'action':'status'},'computer.read',owner_user_id='bob')

    def test_control_approval_and_model_self_approval(self):
        m,a=self.manager();sid=self.start_session(m,a)
        with self.assertRaises(PermissionError):m.invoke('computer','act',{'action':'pointer_click','session_id':sid},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t')
        with self.assertRaises(PermissionError):m.invoke('computer','act',{'action':'pointer_click','session_id':sid,'approved':True},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t')
        m2,_=self.manager(policy=DenyPolicy());
        with self.assertRaises(PermissionError):m2.invoke_read('computer','read',{'action':'status'},'computer.read',owner_user_id='alice')

    def test_restart_no_session_resurrection_and_stale_old_handle(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);m,a=self.manager(store);sid=self.start_session(m,a);self.assertTrue(m.invocations(owner_user_id='alice',connector_id='computer'));a.close();a2=FakeComputerAdapter(owner_user_id='alice');m2=ConnectorManager(Gen2Store(db),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=a2);m2.authorize('computer',['computer.read','computer.act'],owner_user_id='alice',actor='restart',reference='portal');m2.connect('computer',owner_user_id='alice');self.assertEqual(m2.health('computer',owner_user_id='alice')['status'],'HEALTHY');self.assertFalse(a2.active);self.assertIsNone(a2._session_ref)
            with self.assertRaises(ComputerAdapterError):m2.invoke('computer','act',{'action':'pointer_click','session_id':sid},'computer.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())

    def test_provenance_has_no_raw_screenshot_or_session_secret(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);m,a=self.manager(store);sid=self.start_session(m,a);rows=m.invocations(owner_user_id='alice',connector_id='computer');raw=db.read_bytes();self.assertNotIn(b'screencast-pipewire',raw);self.assertNotIn(b'computer-session:',raw);self.assertTrue(rows[0]['arguments_digest']);self.assertEqual(rows[0]['verification_status'],'VERIFIED')

    def test_static_security_no_shell_raw_input_or_forbidden_gui_framework(self):
        text='\n'.join(Path(x).read_text() for x in ('src/sparkle_gen2/infrastructure/devices/computer_adapter.py','src/sparkle_gen2/infrastructure/devices/computer_portal_helper.py')).lower();self.assertNotIn('shell=true',text);self.assertNotIn('/dev/input',text);self.assertNotIn('xdotool',text);self.assertNotIn('ydotool',text);self.assertNotIn('wmctrl',text);self.assertNotIn('selenium',text);self.assertNotIn('playwright',text);self.assertNotIn('xtest',text);self.assertNotIn('/bin/bash',text);self.assertNotIn('/bin/sh',text);self.assertIn("system_python='/usr/bin/python3'",text)

    def test_personalagent_observe_and_control_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');m,a=self.manager(store,owner='user');g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}))
            p=PlanProposal(uuid.uuid4().hex,'computer',[PlanProposalStep('r','Observe screen',['connector_read'],[],['verified'],{'connector_id':'computer','operation':'read','arguments':{'action':'observe','authorize_session':True},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(p),connector_manager=m);res=agent.start('Observe my screen.',user_id='user');self.assertEqual(res['status'],'COMPLETED');sid=a._session_ref
            p2=PlanProposal(uuid.uuid4().hex,'computer',[PlanProposalStep('a','Move pointer',['connector_invoke'],[],['verified'],{'connector_id':'computer','operation':'act','arguments':{'action':'pointer_move','session_id':sid,'x':100,'y':100},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());agent2=PersonalAgent(store,g,planner=StaticPlanner(p2),connector_manager=m);first=agent2.start('Move the pointer safely.',user_id='user');self.assertEqual(first['status'],'WAITING');agent2.decide_approval(first['approvals'][0],'approve',actor='human');done=agent2.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED')

    def test_previous_connectors_linux_boundary_and_models_unchanged(self):
        desc={x.connector_id:{c.operation for c in x.capabilities} for x in DESCRIPTORS};self.assertEqual(desc['gmail'],{'list_messages','get_message_metadata'});self.assertEqual(desc['calendar'],{'list_calendars','list_events','get_event'});self.assertEqual(desc['drive'],{'list_files','get_file_metadata'});self.assertEqual(desc['github'],{'get_user','list_repositories','get_repository','list_repository_contents','list_issues','list_pull_requests','list_workflows'});self.assertEqual(desc['browser'],{'navigate','read','interact'});self.assertEqual(desc['linux'],{'inspect','execute'})
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));mm=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(mm.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
