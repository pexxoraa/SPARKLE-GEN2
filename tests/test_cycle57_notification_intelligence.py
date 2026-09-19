import json,tempfile,threading,unittest,urllib.error,urllib.request,uuid
from pathlib import Path

from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.dashboard import PersonalOperationsService
from sparkle_gen2.models import Approval,ApprovalStatus,Goal,GoalStatus,PlanProposal,PlanProposalStep,RiskLevel
from sparkle_gen2.notifications import NotificationCandidate,NotificationCenter,NotificationDecision,NotificationIntelligenceService
from sparkle_gen2.personal_core import PersonalCore,build_server
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.proactive import ProactiveEventEngine
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store

class G:
    def health(self):return {'available':True,'tools':[],'tool_definitions':[]}
    def retrieve_context(self,*a):return {'source':'test','rendered':''}
    def invoke(self,*a):raise AssertionError('notification intelligence must not invoke privileged Gen-1 tools')

def explain_plan(nid):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('explain','Explain notification',['notification_explain'],[],['persisted notification decision reread'],{'notification_id':nid},30,0)],[{'description':'notification explanation verified','verification_method':'all_steps_verified'}],'LOW',.99,[],'test-only')

def request(url,*,token=None,data=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=headers,method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())

class FakeCoreAgent:
    def __init__(self,notifications):self.notifications=notifications;self.operations=None;self.gen1=G()
    def start(self,*a,**k):raise AssertionError
    def resume(self,*a,**k):raise AssertionError
    def decide_approval(self,*a,**k):raise AssertionError

class Cycle57Tests(unittest.TestCase):
    def service(self,d):
        store=Gen2Store(Path(d)/'g2.db');return store,NotificationIntelligenceService(store)

    def test_candidate_schema_relevance_priority_provenance_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);c=svc.candidate(owner_user_id='alice',event_type='deadline_approaching',subject='Project',title='Deadline',summary='token=supersecret deadline soon',source_kind='goal',source_id='evt1',state={'hours_remaining':4,'api_key':'bad'},correlation={'goal_id':'g1','trace_id':'t1'},provenance={'source':'goal','chain_of_thought':'never'})
            self.assertIsInstance(c,NotificationCandidate);self.assertEqual(c.owner_user_id,'alice');self.assertGreaterEqual(c.relevance,.8);self.assertEqual(c.priority,'CRITICAL');self.assertNotIn('supersecret',json.dumps(c.to_dict()));self.assertNotIn('bad',json.dumps(c.to_dict()));self.assertNotIn('chain_of_thought',json.dumps(c.to_dict()));self.assertEqual(c.correlation['goal_id'],'g1')
            dec=svc.evaluate(c);self.assertIsInstance(dec,NotificationDecision);self.assertEqual(dec.decision,'ESCALATE');self.assertEqual(dec.reason_code,'HIGH_IMPORTANCE_UNRESOLVED');self.assertEqual(len(store.notification_decisions(owner_user_id='alice')),1)

    def test_owner_isolation_and_mark_read_owner_check(self):
        with tempfile.TemporaryDirectory() as d:
            _,svc=self.service(d);dec=svc.process(owner_user_id='alice',event_type='status_change',subject='alpha',title='Alpha changed',summary='changed',source_kind='project',source_id='e1',state={'status':'CHANGED'},relevance=.7,urgency=.6);nid=dec.notification_id
            self.assertEqual(len(svc.attention('alice')),1);self.assertEqual(svc.attention('bob'),[])
            with self.assertRaises(PermissionError):svc.inspect(nid,owner_user_id='bob')
            with self.assertRaises(PermissionError):svc.read(nid,owner_user_id='bob')
            self.assertEqual(svc.read(nid,owner_user_id='alice').status,'READ')

    def test_idempotency_dedup_aggregation_and_meaningful_state_change(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);kw=dict(owner_user_id='u',event_type='connector_failure',subject='gmail',title='Connector unavailable',summary='OAuth unavailable',source_kind='connector',state={'status':'FAILED'},relevance=.7,urgency=.6)
            first=svc.process(source_id='same-event',**kw);again=svc.process(source_id='same-event',**kw);self.assertEqual(first.decision_id,again.decision_id);self.assertEqual(len(store.notification_decisions(owner_user_id='u')),1);self.assertEqual(len(store.notifications()),1)
            repeated=svc.process(source_id='new-event-same-state',**kw);self.assertEqual(repeated.decision,'AGGREGATE');self.assertEqual(repeated.notification_id,first.notification_id);self.assertEqual(NotificationIntelligenceService(store).inspect(first.notification_id,owner_user_id='u')['occurrence_count'],2);self.assertEqual(len(store.notifications()),1)
            changed=svc.process(owner_user_id='u',event_type='connector_failure',subject='gmail',title='Connector degraded',summary='different verified state',source_kind='connector',source_id='state-change',state={'status':'DEGRADED'},relevance=.7,urgency=.6);self.assertEqual(changed.decision,'DELIVER');self.assertNotEqual(changed.notification_id,first.notification_id);self.assertEqual(len(store.notifications()),2)

    def test_low_relevance_suppression_and_decision_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);dec=svc.process(owner_user_id='u',event_type='heartbeat',subject='worker',title='Heartbeat',summary='normal heartbeat',source_kind='system',source_id='h1',state={'status':'OK'});self.assertEqual(dec.decision,'SUPPRESS');self.assertEqual(dec.reason_code,'BELOW_RELEVANCE_THRESHOLD');self.assertIsNone(dec.notification_id);self.assertEqual(store.notifications(),[]);self.assertEqual(store.notification_decisions(owner_user_id='u')[0]['reason_code'],'BELOW_RELEVANCE_THRESHOLD')

    def test_attention_budget_persists_across_restart_but_escalation_still_surfaces(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g2.db';store=Gen2Store(db);svc=NotificationIntelligenceService(store)
            for i in range(4):
                dec=svc.process(owner_user_id='u',event_type='project_change',subject=f'p{i}',title=f'Project {i}',summary='meaningful change',source_kind='project',source_id=f'e{i}',state={'version':i},relevance=.6,urgency=.5);self.assertEqual(dec.decision,'DELIVER')
            restarted=NotificationIntelligenceService(Gen2Store(db));blocked=restarted.process(owner_user_id='u',event_type='project_change',subject='p5',title='Project 5',summary='another change',source_kind='project',source_id='e5',state={'version':5},relevance=.6,urgency=.5);self.assertEqual(blocked.decision,'SUPPRESS');self.assertEqual(blocked.reason_code,'ATTENTION_BUDGET_EXHAUSTED')
            urgent=restarted.process(owner_user_id='u',event_type='approval_waiting',subject='approval-a',title='Approval required',summary='Your decision is required.',source_kind='approval',source_id='a1',state={'status':'PENDING'},relevance=.96,urgency=.9);self.assertEqual(urgent.decision,'ESCALATE');self.assertEqual(len(Gen2Store(db).notifications()),5)

    def test_escalation_cooldown_groups_changed_high_importance_updates(self):
        with tempfile.TemporaryDirectory() as d:
            _,svc=self.service(d);a=svc.process(owner_user_id='u',event_type='approval_waiting',subject='a1',title='Approval required',summary='pending',source_kind='approval',source_id='e1',state={'status':'PENDING','expires':'later'});b=svc.process(owner_user_id='u',event_type='approval_waiting',subject='a1',title='Approval still required',summary='expiry moved closer',source_kind='approval',source_id='e2',state={'status':'PENDING','expires':'soon'});self.assertEqual(a.decision,'ESCALATE');self.assertEqual(b.decision,'AGGREGATE');self.assertEqual(b.reason_code,'ESCALATION_COOLDOWN_AGGREGATED');self.assertEqual(a.notification_id,b.notification_id)

    def test_resolved_before_delivery_suppressed_and_recovery_resolves_prior(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);early=svc.process(owner_user_id='u',event_type='connector_recovered',subject='drive',title='Drive recovered',summary='available',source_kind='connector',source_id='r0',state={'status':'CONNECTED'},resolved=True);self.assertEqual((early.decision,early.reason_code),('SUPPRESS','RESOLVED_BEFORE_DELIVERY'))
            failure=svc.process(owner_user_id='u',event_type='connector_failure',subject='gmail',title='Gmail unavailable',summary='OAuth unavailable',source_kind='connector',source_id='f1',state={'status':'FAILED'},relevance=.7,urgency=.6);recovery=svc.process(owner_user_id='u',event_type='connector_recovered',subject='gmail',title='Gmail recovered',summary='Connector is verified connected again.',source_kind='connector',source_id='r1',state={'status':'CONNECTED'},resolved=True);self.assertEqual(recovery.reason_code,'RECOVERY_VERIFIED');self.assertEqual(svc.inspect(failure.notification_id,owner_user_id='u')['status'],'RESOLVED');self.assertEqual(svc.inspect(recovery.notification_id,owner_user_id='u')['status'],'UNREAD');self.assertEqual([x['notification_id'] for x in svc.attention('u')],[recovery.notification_id]);self.assertEqual(len(store.notification_decisions(owner_user_id='u')),3)

    def test_stale_robot_condition_is_truthfully_labeled(self):
        with tempfile.TemporaryDirectory() as d:
            _,svc=self.service(d);d1=svc.process(owner_user_id='u',event_type='robot_state',subject='Robot-01',title='Robot-01 observation is stale',summary='Latest verified pose is stale; current location is unknown.',source_kind='world_state',source_id='obs1',state={'freshness':'STALE','observation_id':'o1'},stale=True);n=svc.inspect(d1.notification_id,owner_user_id='u');self.assertEqual(d1.reason_code,'STALE_EVIDENCE');self.assertIn('stale',n['why'].lower());self.assertNotIn('currently at',n['body'].lower())

    def test_proactive_engine_integrates_without_second_policy_engine(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);engine=ProactiveEventEngine(store,threshold=.7);event=engine.ingest('deadline_approaching','project alpha',{'hours_remaining':8},.9);dec=svc.process_proactive(engine,event.event_id,owner_user_id='u');self.assertIn(dec.decision,{'ESCALATE','DELIVER'});self.assertEqual(store.load_proactive_event(event.event_id).status,'READY');self.assertEqual((dec.provenance['candidate']['provenance'])['proactive_event_id'],event.event_id)

    def test_restart_keeps_dedup_and_suppression_history(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g2.db';svc=NotificationIntelligenceService(Gen2Store(db));first=svc.process(owner_user_id='u',event_type='status_change',subject='alpha',title='Alpha changed',summary='changed',source_kind='project',source_id='event-1',state={'state':'A'},relevance=.7,urgency=.6);nid=first.notification_id
            restarted=NotificationIntelligenceService(Gen2Store(db));again=restarted.process(owner_user_id='u',event_type='status_change',subject='alpha',title='Alpha changed',summary='changed',source_kind='project',source_id='event-1',state={'state':'A'},relevance=.7,urgency=.6);self.assertEqual(first.decision_id,again.decision_id);self.assertEqual(restarted.attention('u')[0]['notification_id'],nid);self.assertEqual(len(Gen2Store(db).notifications()),1)

    def test_personal_agent_explain_is_readonly_grounded_and_does_not_call_gen1(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);dec=svc.process(owner_user_id='u',event_type='approval_waiting',subject='a1',title='Approval required',summary='Please decide',source_kind='approval',source_id='e1',state={'status':'PENDING'});agent=PersonalAgent(store,G(),planner=StaticPlanner(explain_plan(dec.notification_id)),notification_service=svc);result=agent.start('Why did you notify me?',user_id='u');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['approvals'],[]);self.assertIn('surfaced because',result['text']);self.assertIn('approval is waiting',result['text'].lower());self.assertTrue(any(x['component']=='notification_explain' for x in store.operation_traces(trace_id=result['trace_id'])))

    def test_operations_surface_consumes_final_attention_not_raw_suppressed_volume(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);first=svc.process(owner_user_id='u',event_type='background_failure',subject='job',title='Job failed',summary='failed',source_kind='background_task',source_id='f1',state={'status':'FAILED'});svc.process(owner_user_id='u',event_type='background_failure',subject='job',title='Job failed',summary='failed',source_kind='background_task',source_id='f2',state={'status':'FAILED'});svc.process(owner_user_id='u',event_type='heartbeat',subject='worker',title='Heartbeat',summary='ok',source_kind='system',source_id='h1',state={'status':'OK'});ops=PersonalOperationsService(store,notification_service=svc);snap=ops.snapshot(owner_user_id='u',day='2026-09-19');notes=snap['today']['notifications'];self.assertEqual(len(notes),1);self.assertEqual(notes[0]['notification_id'],first.notification_id);self.assertEqual(notes[0]['occurrence_count'],2);self.assertEqual(notes[0]['decision'],'AGGREGATE')

    def test_notification_mutation_requires_device_scope_and_owner(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);dec=svc.process(owner_user_id='user',event_type='status_change',subject='alpha',title='Alpha changed',summary='changed',source_kind='project',source_id='e1',state={'state':'A'},relevance=.7,urgency=.6);agent=FakeCoreAgent(svc);core=PersonalCore((store,agent,SessionService(store)));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];_,no_scope=request(base+'/api/enroll',data={'code':code,'name':'No notifications','kind':'laptop','os':'Linux','capabilities':['task_status']})
                with self.assertRaises(urllib.error.HTTPError) as denied:request(base+f'/api/notifications/{dec.notification_id}/read',token=no_scope['token'],data={})
                try:self.assertEqual(denied.exception.code,403)
                finally:denied.exception.close()
                code=core.devices.create_enrollment_code()['code'];_,allowed=request(base+'/api/enroll',data={'code':code,'name':'Notifications','kind':'laptop','os':'Linux','capabilities':['notifications']});_,body=request(base+f'/api/notifications/{dec.notification_id}/read',token=allowed['token'],data={});self.assertEqual(body['status'],'READ')
            finally:server.shutdown();server.server_close()

    def test_notification_about_approval_cannot_approve_or_create_authority(self):
        with tempfile.TemporaryDirectory() as d:
            store,svc=self.service(d);stamp=now();g=Goal('g1','dangerous request','dangerous request',status=GoalStatus.WAITING,created_at=stamp,updated_at=stamp,user_id='u');store.save_goal(g);a=Approval('a1','g1','r1','s1','write','workspace_scaffold',RiskLevel.HIGH,stamp,None,ApprovalStatus.PENDING,'trusted-scope');store.save_approval(a);svc.process(owner_user_id='u',event_type='approval_waiting',subject='a1',title='Approval required',summary='A write action is waiting for you.',source_kind='approval',source_id='a1-event',state={'status':'PENDING'},correlation={'goal_id':'g1','approval_id':'a1'});self.assertEqual(store.load_approval('a1').status,ApprovalStatus.PENDING);self.assertEqual(len(store.notification_decisions(owner_user_id='u')),1)

if __name__=='__main__':unittest.main()
