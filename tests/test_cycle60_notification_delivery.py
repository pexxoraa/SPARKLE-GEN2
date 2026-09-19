import json,tempfile,threading,unittest,urllib.error,urllib.request,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path

from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.dashboard import PersonalOperationsService
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.notification_delivery import DeliveryPolicy,NotificationChannelState,NotificationDeliveryAttempt,NotificationDeliveryOrchestrator
from sparkle_gen2.notifications import NotificationCenter,NotificationIntelligenceService
from sparkle_gen2.personal_core import PersonalCore,build_server
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.device_identity import DeviceIdentityService
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.models import PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner


def http(url,*,token=None,data=None):
    h={'Content-Type':'application/json'}
    if token:h['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=h,method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())

class Cycle60Tests(unittest.TestCase):
    def make(self,d,*,desktop=False):
        store=Gen2Store(Path(d)/'g.db');delivery=NotificationDeliveryOrchestrator(store);center=NotificationCenter(store);intel=NotificationIntelligenceService(store,center=center,delivery=delivery)
        device=None
        if desktop:
            ids=DeviceIdentityService(store);code=ids.create_enrollment_code()['code'];device,_=ids.enroll(code,name='Browser',kind='laptop',os_name='PWA',capabilities=['notifications']);delivery.register_channel(owner_user_id='user',channel='desktop',device_id=device.device_id,permission='GRANTED',supported=True,configured=True)
        return store,delivery,intel,device
    def high(self,intel,source='failure-1',summary='Background task failed'):
        return intel.process(owner_user_id='user',event_type='background_failure',subject='Build',title='Build failed',summary=summary,source_kind='background',source_id=source,state={'status':'FAILED'},correlation={'goal_id':'g1'})

    def test_typed_contracts_and_channel_defaults(self):
        c=NotificationChannelState('c','user','dashboard','AVAILABLE','NOT_APPLICABLE',True,'now');a=NotificationDeliveryAttempt('a','d','n','user','dashboard','ACCEPTED','now','now');self.assertEqual(c.channel,'dashboard');self.assertEqual(a.acknowledgement_status,'UNACKNOWLEDGED')
        with tempfile.TemporaryDirectory() as d:
            _,delivery,_,_=self.make(d);states={x['channel']:x for x in delivery.channel_states('user')};self.assertEqual(states['dashboard']['availability'],'AVAILABLE');self.assertEqual(states['voice']['availability'],'UNAVAILABLE');self.assertEqual(states['mobile']['availability'],'UNAVAILABLE')

    def test_notification_intelligence_to_dashboard_and_unavailable_desktop(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,_=self.make(d);decision=self.high(intel);attempts=delivery.attempts('user',decision_id=decision.decision_id);self.assertEqual({x['channel'] for x in attempts},{'dashboard','desktop'});dash=next(x for x in attempts if x['channel']=='dashboard');desk=next(x for x in attempts if x['channel']=='desktop');self.assertEqual(dash['status'],'ACCEPTED');self.assertEqual(desk['status'],'UNAVAILABLE');self.assertEqual(dash['decision_id'],decision.decision_id);self.assertEqual(dash['notification_id'],decision.notification_id)

    def test_low_routes_dashboard_only_and_voice_mobile_never_fake_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            _,delivery,intel,_=self.make(d,desktop=True);decision=intel.process(owner_user_id='user',event_type='misc',subject='FYI',title='FYI',summary='Minor update',source_kind='test',source_id='low',state={'v':1},relevance=.46,urgency=.1);attempts=delivery.attempts('user',decision_id=decision.decision_id);self.assertEqual([x['channel'] for x in attempts],['dashboard']);self.assertNotIn('voice',{x['channel'] for x in attempts});self.assertNotIn('mobile',{x['channel'] for x in attempts})

    def test_granted_desktop_pending_result_and_ack_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,device=self.make(d,desktop=True);decision=self.high(intel);desk=next(x for x in delivery.attempts('user',decision_id=decision.decision_id) if x['channel']=='desktop');self.assertEqual(desk['status'],'PENDING');self.assertEqual(len(delivery.pending('user',channel='desktop',device_id=device.device_id)),1);accepted=delivery.record_result(desk['attempt_id'],owner_user_id='user',device_id=device.device_id,status='ACCEPTED',channel_reference='service-worker:test');self.assertEqual(accepted['status'],'ACCEPTED');self.assertEqual(accepted['acknowledgement_status'],'UNACKNOWLEDGED');acked=delivery.acknowledge(desk['attempt_id'],owner_user_id='user',device_id=device.device_id);self.assertEqual(acked['status'],'ACKNOWLEDGED');self.assertTrue(acked['acknowledged_at'])

    def test_permission_denied_and_unknown_fail_closed_to_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,_=self.make(d);ids=DeviceIdentityService(store);code=ids.create_enrollment_code()['code'];dev,_=ids.enroll(code,name='B',kind='laptop',os_name='PWA',capabilities=['notifications']);denied=delivery.register_channel(owner_user_id='user',channel='desktop',device_id=dev.device_id,permission='DENIED',supported=True);self.assertEqual(denied.availability,'PERMISSION_DENIED');decision=self.high(intel);desk=next(x for x in delivery.attempts('user',decision_id=decision.decision_id) if x['channel']=='desktop');self.assertEqual(desk['status'],'UNAVAILABLE')
        with tempfile.TemporaryDirectory() as d:
            store,delivery,_,_=self.make(d);ids=DeviceIdentityService(store);code=ids.create_enrollment_code()['code'];dev,_=ids.enroll(code,name='B',kind='laptop',os_name='PWA',capabilities=['notifications']);unknown=delivery.register_channel(owner_user_id='user',channel='desktop',device_id=dev.device_id,permission='UNKNOWN',supported=True);self.assertEqual(unknown.availability,'PERMISSION_UNKNOWN')

    def test_quiet_hours_suppress_normal_desktop_but_not_high(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,device=self.make(d,desktop=True);store.save_setting('notification_delivery_policy:user',{'quiet_hours':{'enabled':True,'start':'00:00','end':'23:59'}});normal=intel.process(owner_user_id='user',event_type='misc',subject='N',title='Normal',summary='normal',source_kind='test',source_id='n1',state={'x':1},relevance=.6,urgency=.5);self.assertEqual([x['channel'] for x in delivery.attempts('user',decision_id=normal.decision_id)],['dashboard','desktop']);desk=next(x for x in delivery.attempts('user',decision_id=normal.decision_id) if x['channel']=='desktop');self.assertEqual(desk['status'],'UNAVAILABLE');high=self.high(intel,'h2');self.assertEqual(next(x for x in delivery.attempts('user',decision_id=high.decision_id) if x['channel']=='desktop')['status'],'PENDING')

    def test_idempotency_restart_and_stale_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g.db';store,delivery,intel,device=self.make(d,desktop=True);decision=self.high(intel);before=delivery.attempts('user',decision_id=decision.decision_id);delivery.handle_decision(decision);self.assertEqual([x['attempt_id'] for x in before],[x['attempt_id'] for x in delivery.attempts('user',decision_id=decision.decision_id)]);restarted=NotificationDeliveryOrchestrator(Gen2Store(db));restarted.recover_all();self.assertEqual(len(restarted.attempts('user',decision_id=decision.decision_id)),len(before));desk=next(x for x in restarted.attempts('user',decision_id=decision.decision_id) if x['channel']=='desktop');desk['created_at']=(datetime.now(UTC)-timedelta(minutes=30)).isoformat();restarted.store.save_notification_delivery_attempt(desk);restarted.expire_stale('user');self.assertEqual(restarted.store.notification_delivery_attempt(desk['attempt_id'])['status'],'EXPIRED')

    def test_retry_links_same_decision_and_does_not_duplicate_active_retry(self):
        with tempfile.TemporaryDirectory() as d:
            _,delivery,intel,device=self.make(d,desktop=True);decision=self.high(intel);desk=next(x for x in delivery.attempts('user',decision_id=decision.decision_id) if x['channel']=='desktop');delivery.record_result(desk['attempt_id'],owner_user_id='user',device_id=device.device_id,status='FAILED',error='browser failed');retry=delivery.retry(desk['attempt_id'],owner_user_id='user');self.assertEqual(retry['decision_id'],desk['decision_id']);self.assertEqual(retry['notification_id'],desk['notification_id']);self.assertEqual(retry['parent_attempt_id'],desk['attempt_id']);self.assertEqual(retry['status'],'PENDING');again=delivery.retry(desk['attempt_id'],owner_user_id='user');self.assertEqual(again['attempt_id'],retry['attempt_id'])

    def test_sensitive_payload_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,_,device=self.make(d,desktop=True);center=NotificationCenter(store);n=center.create('security','Credential reference','token=SECRET123 password=hunter2','HIGH',owner_user_id='user',provenance={'classification':'SENSITIVE'});decision={'decision_id':'d-sensitive','candidate_id':'c-sensitive','owner_user_id':'user','decision':'DELIVER','reason_code':'X','notification_id':n.notification_id};delivery.handle_decision(decision);desk=next(x for x in delivery.attempts('user',notification_id=n.notification_id) if x['channel']=='desktop');blob=json.dumps(desk['payload']);self.assertEqual(desk['payload']['title'],'SPARKLE notification');self.assertIn('protected',desk['payload']['body'].lower());self.assertNotIn('SECRET123',blob);self.assertNotIn('hunter2',blob);self.assertNotIn('nvapi-',blob)

    def test_owner_device_and_revocation_security(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,device=self.make(d,desktop=True);decision=self.high(intel);desk=next(x for x in delivery.attempts('user',decision_id=decision.decision_id) if x['channel']=='desktop')
            with self.assertRaises(PermissionError):delivery.record_result(desk['attempt_id'],owner_user_id='other',device_id=device.device_id,status='ACCEPTED')
            with self.assertRaises(PermissionError):delivery.record_result(desk['attempt_id'],owner_user_id='user',device_id='wrong',status='ACCEPTED')
            DeviceIdentityService(store).revoke(device.device_id);state=next(x for x in delivery.channel_states('user') if x['channel']=='desktop');self.assertEqual(state['availability'],'UNAVAILABLE')

    def test_operations_snapshot_exposes_delivery_state(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,_=self.make(d);self.high(intel);svc=PersonalOperationsService(store,notification_service=intel);snap=svc.snapshot(owner_user_id='user');view=snap['operations']['notification_delivery'];self.assertEqual(view['status'],'AVAILABLE');self.assertTrue(view['failures']);self.assertTrue(snap['intelligence']['notification_channels']['items'])

    def test_personalagent_policy_marks_inspection_read_only_and_retry_ack_state_changing(self):
        p=PolicyEngine();self.assertEqual(p.evaluate('notification_delivery_inspect','u','x','now')[0].effect,PermissionEffect.ALLOW);self.assertEqual(p.evaluate('notification_channels_inspect','u','x','now')[0].effect,PermissionEffect.ALLOW);self.assertEqual(p.evaluate('notification_delivery_retry','u','x','now')[0].effect,PermissionEffect.REQUIRE_APPROVAL);self.assertEqual(p.evaluate('notification_acknowledge','u','x','now')[0].effect,PermissionEffect.REQUIRE_APPROVAL)

    def test_personalagent_read_inspection_and_approval_gated_acknowledgement(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,_=self.make(d);decision=self.high(intel);dash=next(x for x in delivery.attempts('user',decision_id=decision.decision_id) if x['channel']=='dashboard')
            inspect_plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('channels','Inspect notification channels',['notification_channels_inspect'],[],['persisted channel state reread'],{},30,0)],[{'description':'channels read','verification_method':'all_steps_verified'}],'LOW',.99,[],'test')
            agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(inspect_plan),notification_service=intel);read=agent.start('What notification channels are available?',user_id='user');self.assertEqual(read['status'],'COMPLETED');self.assertEqual(read['approvals'],[]);self.assertIn('Notification channels:',read['text'])
            ack_plan=PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('ack','Acknowledge exact notification delivery',['notification_acknowledge'],[],['persisted acknowledged delivery reread'],{'attempt_id':dash['attempt_id']},30,0)],[{'description':'ack verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],'test')
            agent.planner=StaticPlanner(ack_plan);pending=agent.start('Acknowledge that notification.',user_id='user');self.assertEqual(pending['status'],'WAITING');self.assertEqual(store.notification_delivery_attempt(dash['attempt_id'])['status'],'ACCEPTED');agent.decide_approval(pending['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(pending['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(store.notification_delivery_attempt(dash['attempt_id'])['status'],'ACKNOWLEDGED')

    def test_authenticated_http_desktop_delivery_result_ack_and_scope_denial(self):
        with tempfile.TemporaryDirectory() as d:
            store,delivery,intel,_=self.make(d);agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),notification_service=intel);core=PersonalCore((store,agent,SessionService(store)));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];_,en=http(base+'/api/enroll',data={'code':code,'name':'Web','kind':'laptop','os':'PWA','capabilities':['notifications']});token=en['token'];_,state=http(base+'/api/notification-channels/desktop',token=token,data={'supported':True,'permission':'granted'});self.assertEqual(state['availability'],'AVAILABLE');decision=self.high(intel);_,pending=http(base+'/api/notification-deliveries/pending?channel=desktop',token=token);self.assertEqual(len(pending['attempts']),1);aid=pending['attempts'][0]['attempt_id'];_,accepted=http(base+f'/api/notification-deliveries/{aid}/result',token=token,data={'status':'ACCEPTED','channel_reference':'service-worker:test'});self.assertEqual(accepted['status'],'ACCEPTED');_,acked=http(base+f'/api/notification-deliveries/{aid}/acknowledge',token=token,data={});self.assertEqual(acked['status'],'ACKNOWLEDGED')
                code=core.devices.create_enrollment_code()['code'];_,limited=http(base+'/api/enroll',data={'code':code,'name':'NoNotify','kind':'laptop','os':'PWA','capabilities':['conversation']});
                with self.assertRaises(urllib.error.HTTPError) as denied:http(base+'/api/notification-channels',token=limited['token'])
                denied.exception.close()
            finally:server.shutdown();server.server_close()

    def test_pwa_contains_real_permission_show_and_click_ack_paths(self):
        root=Path(__file__).parents[1]/'src/sparkle_gen2/web';app=(root/'app.js').read_text();sw=(root/'service-worker.js').read_text();html=(root/'index.html').read_text();self.assertIn('Notification.requestPermission()',app);self.assertIn('showNotification',app);self.assertIn('/api/notification-channels/desktop',app);self.assertIn('notificationclick',sw);self.assertIn('/acknowledge',sw);self.assertIn('enable-desktop-notifications',html)

if __name__=='__main__':unittest.main()
