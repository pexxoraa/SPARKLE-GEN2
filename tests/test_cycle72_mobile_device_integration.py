import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from sparkle.secrets import SecretResolver
from sparkle_gen2.connector_catalog import DESCRIPTORS,build_default_connectors
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.mobile_connector import MobileDeviceAdapter,READ_ACTIONS,CONTROL_ACTIONS
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import ApprovalStatus,PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class Target:
    def __init__(self):self.connected=True;self.requests=[];self.closed=False
    def status(self):return {'connected':self.connected,'status':'CONNECTED' if self.connected else 'OFFLINE'}
    def request_notification(self,payload):self.requests.append(('notification',dict(payload)));return {'accepted':True,'request_reference':'notif-ref'}
    def request_sync(self,payload):self.requests.append(('sync',dict(payload)));return {'accepted':True,'request_reference':'sync-ref'}
    def verify(self,action,result):return {'verified':result.get('accepted') is True,'method':'fake target reread','action':action}

class Approval:
    def __init__(self,goal='g',task='t'):self.status=ApprovalStatus.APPROVED;self.goal_id=goal;self.task_run_id=task;self.approval_id='approval-mobile'

class Cycle72MobileTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='mobile')
    def record(self,**overrides):
        base={'device_id':'dev-mobile-1','name':'Phone','kind':'mobile','os_name':'Android','capabilities':['conversation','notifications','task_status'],'status':'ONLINE','created_at':'now','last_seen':'now','revoked_at':None}
        base.update(overrides);return base
    def manager(self,store=None,*,owner='alice',record=None,target=None):
        a=MobileDeviceAdapter(owner_user_id=owner,device_record=record or self.record(),target=target or Target());m=ConnectorManager(store,policy=PolicyEngine(),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=a);auth=a.authorize();m.authorize('mobile',['mobile.read','mobile.act'],owner_user_id=owner,actor='trusted_mobile_binding',reference=auth['authorization_reference']);m.connect('mobile',owner_user_id=owner);return m,a

    def test_descriptor_exact_and_policy(self):
        d=self.descriptor();caps={x.operation:x for x in d.capabilities};self.assertTrue(d.device_scoped);self.assertEqual(set(caps),{'read','act'});self.assertEqual(caps['read'].mode.value,'READ');self.assertEqual(caps['read'].policy_capability,'mobile.read');self.assertEqual(caps['act'].mode.value,'CONTROL');self.assertEqual(caps['act'].policy_capability,'mobile.act')
        p,r=PolicyEngine().evaluate('mobile.read','u','mobile:read',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');p2,_=PolicyEngine().evaluate('mobile.act','u','mobile:act',now());self.assertEqual(p2.effect,PermissionEffect.REQUIRE_APPROVAL)

    def test_no_target_or_revoked_device_is_not_configured(self):
        self.assertFalse(MobileDeviceAdapter(owner_user_id='u',device_record=self.record(),target=None).configured())
        self.assertFalse(MobileDeviceAdapter(owner_user_id='u',device_record=self.record(status='REVOKED',revoked_at='now'),target=Target()).configured())

    def test_read_actions_are_bounded(self):
        m,a=self.manager()
        for action in READ_ACTIONS:
            with self.subTest(action=action):
                r=m.invoke_read('mobile','read',{'action':action},'mobile.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertTrue(r['verification']['verified'])
        info=m.invoke_read('mobile','read',{'action':'device_info'},'mobile.read',owner_user_id='alice')['result']['result']['device'];self.assertTrue(info['device_reference'].startswith('mobile-device:'));self.assertNotIn('device_id',info);self.assertNotIn('name',info)

    def test_control_actions_require_approval_and_verify(self):
        m,a=self.manager()
        with self.assertRaises(PermissionError):m.invoke('mobile','act',{'action':'request_sync','sync_scope':'state'},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t')
        with self.assertRaises(PermissionError):m.invoke('mobile','act',{'action':'request_sync','sync_scope':'state','approved':True},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t')
        r=m.invoke('mobile','act',{'action':'request_notification','notification_id':'n-1'},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(r['status'],'VERIFIED');self.assertTrue(r['verification']['verified']);self.assertEqual(a.target.requests[-1][0],'notification')

    def test_sync_scope_allowlist_and_no_enrollment_revoke_api(self):
        m,a=self.manager()
        for scope in ('state','notifications','sessions','task_status'):
            r=m.invoke('mobile','act',{'action':'request_sync','sync_scope':scope},'mobile.act',owner_user_id='alice',goal_id=scope,task_run_id=scope,approval=Approval(scope,scope));self.assertEqual(r['status'],'VERIFIED')
        with self.assertRaises(PermissionError):m.invoke('mobile','act',{'action':'request_sync','sync_scope':'device_management'},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())
        for action in ('enroll','revoke','expand_permissions','install','execute','shell'):
            with self.subTest(action=action),self.assertRaises(PermissionError):m.invoke('mobile','act',{'action':action},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())

    def test_owner_device_isolation(self):
        m,a=self.manager()
        with self.assertRaises(PermissionError):m.invoke_read('mobile','read',{'action':'status'},'mobile.read',owner_user_id='bob')
        with self.assertRaises(PermissionError):m.invoke_read('mobile','read',{'action':'status'},'mobile.read',owner_user_id='alice',device_id='different-device')

    def test_revocation_closes_adapter_and_blocks_use(self):
        m,a=self.manager();rv=m.revoke('mobile',owner_user_id='alice',actor='human');self.assertEqual(rv['connector_id'],'mobile');self.assertTrue(a._closed);self.assertEqual(m.health('mobile',owner_user_id='alice')['status'],'REVOKED')
        with self.assertRaises(PermissionError):m.invoke_read('mobile','read',{'action':'status'},'mobile.read',owner_user_id='alice')

    def test_persistence_contains_no_device_token_or_payload_content(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);m,a=self.manager(store);m.invoke('mobile','act',{'action':'request_notification','notification_id':'private-notification-id'},'mobile.act',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());raw=db.read_bytes();self.assertNotIn(b'private-notification-id',raw);self.assertNotIn(b'device-token',raw);rows=m.invocations(owner_user_id='alice',connector_id='mobile');self.assertEqual(rows[0]['verification_status'],'VERIFIED');self.assertTrue(rows[0]['arguments_digest'])

    def test_restart_does_not_invent_target_or_session(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store=Gen2Store(db);m,a=self.manager(store);m.invoke_read('mobile','read',{'action':'status'},'mobile.read',owner_user_id='alice');m2=ConnectorManager(Gen2Store(db),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor());h=m2.health('mobile',owner_user_id='alice');self.assertEqual(h['status'],'EXTERNALLY_BLOCKED');self.assertFalse(h['configured']);self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='mobile')),1)

    def test_personalagent_read_and_control_paths(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');m,a=self.manager(store,owner='user');g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}))
            pr=PlanProposal(uuid.uuid4().hex,'mobile',[PlanProposalStep('r','Read mobile',['connector_read'],[],['verified'],{'connector_id':'mobile','operation':'read','arguments':{'action':'status'},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.9,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(pr),connector_manager=m);res=agent.start('Check my mobile connection.',user_id='user');self.assertEqual(res['status'],'COMPLETED');self.assertEqual(res['approvals'],[])
            pr2=PlanProposal(uuid.uuid4().hex,'mobile',[PlanProposalStep('a','Request sync',['connector_invoke'],[],['verified'],{'connector_id':'mobile','operation':'act','arguments':{'action':'request_sync','sync_scope':'state'},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.9,[],now());agent2=PersonalAgent(store,g,planner=StaticPlanner(pr2),connector_manager=m);first=agent2.start('Sync my mobile state.',user_id='user');self.assertEqual(first['status'],'WAITING');agent2.decide_approval(first['approvals'][0],'approve',actor='human');done=agent2.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED')

    def test_default_composition_stays_blocked_without_target_and_accepts_trusted_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g.db');m=build_default_connectors(store=store,policy=PolicyEngine(),owner_user_id='alice',activate_external=False);h=m.health('mobile',owner_user_id='alice');self.assertEqual(h['status'],'EXTERNALLY_BLOCKED');self.assertFalse(h['configured'])
            a=MobileDeviceAdapter(owner_user_id='alice',device_record=self.record(),target=Target());m2=build_default_connectors(store=Gen2Store(Path(d)/'g2.db'),policy=PolicyEngine(),owner_user_id='alice',activate_external=False,mobile_adapter=a);h2=m2.health('mobile',owner_user_id='alice');self.assertEqual(h2['status'],'HEALTHY');self.assertEqual(h2['authorization_state'],'AUTHORIZED')

    def test_existing_connectors_and_models_unchanged(self):
        desc={x.connector_id:{c.operation for c in x.capabilities} for x in DESCRIPTORS};self.assertEqual(desc['gmail'],{'list_messages','get_message_metadata'});self.assertEqual(desc['calendar'],{'list_calendars','list_events','get_event'});self.assertEqual(desc['drive'],{'list_files','get_file_metadata'});self.assertEqual(desc['github'],{'get_user','list_repositories','get_repository','list_repository_contents','list_issues','list_pull_requests','list_workflows'});self.assertEqual(desc['browser'],{'navigate','read','interact'});self.assertEqual(desc['linux'],{'inspect','execute'});self.assertEqual(desc['computer'],{'read','act'})
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));mm=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(mm.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
