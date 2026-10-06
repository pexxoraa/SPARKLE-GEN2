import json,tempfile,unittest,uuid
from datetime import UTC,datetime
from pathlib import Path
from types import SimpleNamespace
import httplib2
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sparkle.secrets import SecretResolver
from sparkle_gen2.calendar_connector import (CALENDAR_READONLY_SCOPE,CalendarConnectorError,CalendarCredentialSource,CalendarReadAdapter)
from sparkle_gen2.connector_catalog import DESCRIPTORS
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.context_sources import PersonalContextAssembler
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.dashboard import PersonalOperationsService
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class FakeCred:
    def __init__(self,*,expired=False,valid=True,refresh_token='refresh-secret',refresh_error=None):self.expired=expired;self.valid=valid;self.refresh_token=refresh_token;self.refresh_error=refresh_error;self.refresh_calls=0
    def has_scopes(self,scopes):return list(scopes)==[CALENDAR_READONLY_SCOPE]
    def refresh(self,request):
        self.refresh_calls+=1
        if self.refresh_error:raise self.refresh_error
        self.expired=False;self.valid=True

class FakeSource:
    secret_ref='SPARKLE_CALENDAR_TOKEN_FILE'
    def __init__(self,cred=None,configured=True,error=None):self.cred=cred or FakeCred();self.is_configured=configured;self.error=error
    def configured(self):return self.is_configured
    def load(self):
        if self.error:raise self.error
        return self.cred

class Req:
    def __init__(self,value=None,error=None):self.value=value;self.error=error
    def execute(self):
        if self.error:raise self.error
        return self.value

class CalendarListApi:
    def __init__(self,parent):self.parent=parent
    def list(self,**kwargs):self.parent.calls.append(('calendar_list',dict(kwargs)));return Req(self.parent.calendar_list_value,self.parent.calendar_list_error)
    def get(self,**kwargs):
        self.parent.calls.append(('calendar_get',dict(kwargs)));cid=kwargs['calendarId'];item=next((x for x in self.parent.calendar_list_value.get('items',[]) if x.get('id')==cid),None);return Req(item,self.parent.calendar_get_error)

class EventsApi:
    def __init__(self,parent):self.parent=parent
    def list(self,**kwargs):self.parent.calls.append(('events_list',dict(kwargs)));return Req(self.parent.events_list_value,self.parent.events_list_error)
    def get(self,**kwargs):
        self.parent.calls.append(('event_get',dict(kwargs)));eid=kwargs['eventId'];value=self.parent.event_get_values.pop(0) if len(self.parent.event_get_values)>1 else self.parent.event_get_values[0];return Req(value,self.parent.event_get_error)

class FakeService:
    def __init__(self,*,calendar_items=None,events=None,event=None):
        self.calendar_list_value={'items':calendar_items or [{'id':'primary@example.invalid','summary':'Private Calendar','accessRole':'owner','primary':True},{'id':'other@example.invalid','summary':'Other','accessRole':'reader'}]}
        self.events_list_value={'items':events if events is not None else [self.timed()]};self.event_get_values=[event or self.timed()];self.calls=[];self.calendar_list_error=None;self.calendar_get_error=None;self.events_list_error=None;self.event_get_error=None
    @staticmethod
    def timed(eid='evt123',summary='Private meeting'):return {'id':eid,'status':'confirmed','summary':summary,'start':{'dateTime':'2026-09-20T10:00:00+05:30'},'end':{'dateTime':'2026-09-20T11:00:00+05:30'},'updated':'2026-09-19T10:00:00Z','description':'PRIVATE-DESCRIPTION-MUST-NOT-ESCAPE','attendees':[{'email':'private@example.invalid'}]}
    @staticmethod
    def all_day(eid='allday1'):return {'id':eid,'status':'confirmed','summary':'Private all day','start':{'date':'2026-09-20'},'end':{'date':'2026-09-21'},'updated':'2026-09-19T10:00:00Z'}
    def calendarList(self):return CalendarListApi(self)
    def events(self):return EventsApi(self)

class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        permission,risk=super().evaluate(capability,subject,scope,timestamp)
        if capability=='calendar.read':permission.effect=PermissionEffect.DENY
        return permission,risk

class Cycle65CalendarReadTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='calendar')
    def manager(self,store=None,*,owner='alice',service=None,source=None,policy=None):
        source=source or FakeSource();service=service or FakeService();adapter=CalendarReadAdapter(source,service_factory=lambda _c:service,clock=lambda:datetime(2026,9,20,0,0,tzinfo=UTC));auth=adapter.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=SecretResolver({}),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('calendar',['calendar.read'],owner_user_id=owner,actor='oauth-test',reference=auth['authorization_reference']);m.connect('calendar',owner_user_id=owner);return m,adapter,service

    def test_registration_is_exactly_read_only_google_calendar(self):
        d=self.descriptor();self.assertEqual(d.provider_system,'Google Calendar API');self.assertEqual(d.secret_refs,('SPARKLE_CALENDAR_TOKEN_FILE',));ops={x.operation for x in d.capabilities};self.assertEqual(ops,{'list_calendars','list_events','get_event'});self.assertTrue(all(x.scope=='calendar.read' and x.mode.value=='READ' and x.policy_capability=='calendar.read' for x in d.capabilities));self.assertFalse({'create_event','update_event','delete_event','move_event','invite','send'} & ops)

    def test_missing_credential_and_authorization_success(self):
        a=CalendarReadAdapter(FakeSource(configured=False),service_factory=lambda _c:FakeService());h=a.health();self.assertFalse(h['ok']);self.assertEqual(h['authorization_state'],'NOT_CONFIGURED')
        m,_,_=self.manager();row=m.inspect('calendar',owner_user_id='alice');self.assertTrue(row['configured']);self.assertTrue(row['authorized']);self.assertTrue(row['connected']);self.assertEqual(m.health('calendar',owner_user_id='alice')['status'],'HEALTHY')

    def test_refresh_success_expired_revoked_and_refresh_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'token.json';p.write_text('{}');good=FakeCred(expired=True,valid=False);src=CalendarCredentialSource(path=p,loader=lambda *_a,**_k:good,request_factory=lambda:object());self.assertIs(src.load(),good);self.assertEqual(good.refresh_calls,1)
            no_refresh=FakeCred(expired=True,valid=False,refresh_token=None);src=CalendarCredentialSource(path=p,loader=lambda *_a,**_k:no_refresh)
            with self.assertRaises(CalendarConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_EXPIRED')
            revoked=FakeCred(expired=True,valid=False,refresh_error=RefreshError('invalid_grant'));src=CalendarCredentialSource(path=p,loader=lambda *_a,**_k:revoked,request_factory=lambda:object())
            with self.assertRaises(CalendarConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_REVOKED')

    def test_policy_allow_low_deny_and_revocation(self):
        p,r=PolicyEngine().evaluate('calendar.read','alice','calendar:list_events',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');m,_,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')
        m,_,_=self.manager();m.revoke('calendar',owner_user_id='alice',actor='human')
        with self.assertRaises(PermissionError):m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')

    def test_list_calendars_is_bounded_and_verified(self):
        m,_,service=self.manager();r=m.invoke_read('calendar','list_calendars',{'max_results':2},'calendar.read',owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(value['result_count'],2);self.assertEqual(set(value['calendars'][0]),{'calendar_id','summary','access_role','primary'});self.assertTrue(r['verification']['verified']);self.assertEqual(r['verification']['calendar_count'],2);self.assertEqual(m.invocations(owner_user_id='alice',connector_id='calendar')[-1]['external_reference'],'calendar:calendarList.list')
        for invalid in (0,26,True,'2'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):m.invoke_read('calendar','list_calendars',{'max_results':invalid},'calendar.read',owner_user_id='alice')

    def test_list_events_default_window_bounded_and_timed_event(self):
        m,_,service=self.manager();r=m.invoke_read('calendar','list_events',{'calendar_id':'primary','max_results':1},'calendar.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(value['result_count'],1);event=value['events'][0];self.assertFalse(event['all_day']);self.assertIn('dateTime',event['start']);call=next(x for x in service.calls if x[0]=='events_list');self.assertEqual(call[1]['calendarId'],'primary');self.assertTrue(call[1]['singleEvents']);self.assertEqual(call[1]['orderBy'],'startTime');self.assertIn('timeMin',call[1]);self.assertIn('timeMax',call[1])

    def test_explicit_window_validation_and_all_day_event(self):
        service=FakeService(events=[FakeService.all_day()]);service.event_get_values=[FakeService.all_day()];m,_,_=self.manager(service=service);r=m.invoke_read('calendar','list_events',{'time_min':'2026-09-20T00:00:00Z','time_max':'2026-09-21T00:00:00Z'},'calendar.read',owner_user_id='alice');self.assertTrue(r['result']['result']['events'][0]['all_day']);self.assertEqual(r['result']['result']['events'][0]['start'],{'date':'2026-09-20'})
        for args in ({'time_min':'2026-09-20T00:00:00Z'},{'time_min':'2026-09-21T00:00:00Z','time_max':'2026-09-20T00:00:00Z'},{'time_min':'2026-01-01T00:00:00Z','time_max':'2027-12-31T00:00:00Z'}):
            with self.subTest(args=args),self.assertRaises(ValueError):m.invoke_read('calendar','list_events',args,'calendar.read',owner_user_id='alice')

    def test_get_event_bounded_details_and_verified(self):
        event=FakeService.timed();service=FakeService(event=event);service.event_get_values=[event,event];m,_,_=self.manager(service=service);r=m.invoke_read('calendar','get_event',{'calendar_id':'primary','event_id':'evt123'},'calendar.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(set(value),{'event_id','calendar_id','status','summary','start','end','all_day','updated'});self.assertNotIn('description',json.dumps(value));self.assertNotIn('attendees',json.dumps(value));self.assertTrue(r['verification']['event_sha256'])

    def test_malformed_provider_data_fails_closed(self):
        bad_events=[
          {'id':None,'status':'confirmed','summary':'x','start':{'date':'2026-09-20'},'end':{'date':'2026-09-21'}},
          {'id':'e','status':'unknown','summary':'x','start':{'date':'2026-09-20'},'end':{'date':'2026-09-21'}},
          {'id':'e','status':'confirmed','summary':'x','start':{},'end':{'date':'2026-09-21'}},
          {'id':'e','status':'confirmed','summary':'x','start':{'date':'2026-09-21'},'end':{'date':'2026-09-20'}},
        ]
        for raw in bad_events:
            service=FakeService(events=[raw]);m,_,_=self.manager(service=service)
            with self.subTest(raw=raw),self.assertRaises((CalendarConnectorError,ValueError)):m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')
        service=FakeService(calendar_items=[{'id':'x','summary':'No primary','accessRole':'owner'}]);adapter=CalendarReadAdapter(FakeSource(),service_factory=lambda _c:service)
        with self.assertRaises(CalendarConnectorError):adapter.authorize()

    def test_wrong_account_identity_fails_verification(self):
        service=FakeService();m,adapter,_=self.manager(service=service);result=adapter.invoke('list_events',{'max_results':1});service.calendar_list_value={'items':[{'id':'different@example.invalid','summary':'x','accessRole':'owner','primary':True}]};evidence=adapter.verify('list_events',result);self.assertFalse(evidence['verified']);self.assertEqual(evidence['reason'],'authorized_account_identity_mismatch')

    def test_authorization_expiry_and_revocation_propagate_to_manager_health(self):
        for category,expected in (('AUTH_EXPIRED','EXPIRED'),('AUTH_REVOKED','REVOKED')):
            source=FakeSource(error=CalendarConnectorError(category,'safe'));adapter=CalendarReadAdapter(source,service_factory=lambda _c:FakeService());m=ConnectorManager(policy=PolicyEngine(),default_owner='alice');m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('calendar',['calendar.read'],owner_user_id='alice',actor='prior-oauth',reference='calendar-account:opaque');h=m.health('calendar',owner_user_id='alice');self.assertEqual(h['authorization_state'],expected);self.assertNotEqual(h.get('health'),'HEALTHY')

    def test_provider_failure_timeout_rate_limit_and_auth_errors(self):
        service=FakeService();m,_,_=self.manager(service=service);service.events_list_error=RuntimeError('private provider details')
        with self.assertRaises(CalendarConnectorError) as cm:m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'CALENDAR_API_ERROR');row=m.invocations(owner_user_id='alice',connector_id='calendar')[-1];self.assertNotIn('private provider details',json.dumps(row))
        service=FakeService();m,_,_=self.manager(service=service);service.events_list_error=TimeoutError('slow')
        with self.assertRaises(CalendarConnectorError) as cm:m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'TIMEOUT')
        for status,category in ((429,'CALENDAR_RATE_LIMIT'),(403,'CALENDAR_RATE_LIMIT'),(401,'AUTH_EXPIRED')):
            service=FakeService();m,_,_=self.manager(service=service);service.events_list_error=HttpError(httplib2.Response({'status':str(status)}),b'{}')
            with self.subTest(status=status),self.assertRaises(CalendarConnectorError) as cm:m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice')
            self.assertEqual(cm.exception.category,category)

    def test_owner_isolation_restart_and_invocation_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g2.sqlite3';store=Gen2Store(path);m,_,_=self.manager(store);m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='calendar')),1);self.assertEqual(m.invocations(owner_user_id='bob',connector_id='calendar'),[])
            with self.assertRaises(PermissionError):m.invoke_read('calendar','list_events',{},'calendar.read',owner_user_id='bob')
            service2=FakeService();adapter2=CalendarReadAdapter(FakeSource(),service_factory=lambda _c:service2,clock=lambda:datetime(2026,9,20,tzinfo=UTC));adapter2.authorize();m2=ConnectorManager(Gen2Store(path),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=adapter2);self.assertEqual(m2.health('calendar',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='calendar')),1)

    def test_no_credentials_or_extended_private_event_data_persist(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');service=FakeService();m,_,_=self.manager(store,service=service);m.invoke_read('calendar','get_event',{'event_id':'evt123'},'calendar.read',owner_user_id='alice');raw=Path(store.path).read_bytes()
            for secret in (b'access-secret-token',b'refresh-secret',b'client-secret',b'Authorization',b'PRIVATE-DESCRIPTION-MUST-NOT-ESCAPE',b'private@example.invalid',b'Private meeting'):
                self.assertNotIn(secret,raw)
            row=store.connector_invocations(owner_user_id='alice',connector_id='calendar')[0];self.assertEqual(row['verification_status'],'VERIFIED');self.assertIn('event_sha256',row['verification']);self.assertNotIn('Private meeting',json.dumps(row))

    def test_personalagent_read_path_requires_no_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store,owner='user');proposal=PlanProposal(uuid.uuid4().hex,'calendar',[PlanProposalStep('cal-read','List upcoming Calendar events',['connector_read'],[],['verified Calendar read'],{'connector_id':'calendar','operation':'list_events','arguments':{'calendar_id':'primary','max_results':1},'classification':'PRIVATE'},30,0)],[{'description':'Calendar result verified','verification_method':'all_steps_verified'}],'LOW',.95,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);result=agent.start('What is on my calendar today?',user_id='user');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['approvals'],[]);rows=store.connector_invocations(owner_user_id='user',connector_id='calendar');self.assertEqual(rows[0]['verification_status'],'VERIFIED');self.assertEqual(rows[0]['goal_id'],result['goal_id'])

    def test_context_minimization_and_operations_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store);ctx=PersonalContextAssembler(connectors=m).gather('What meetings do I have tomorrow?',owner_user_id='alice');items=[x for x in ctx['items'] if x['source']=='calendar'];self.assertTrue(items);self.assertLessEqual(len(items),1);self.assertNotIn('PRIVATE-DESCRIPTION-MUST-NOT-ESCAPE',json.dumps(ctx));before=len(m.invocations(owner_user_id='alice',connector_id='calendar'));PersonalContextAssembler(connectors=m).gather('Refactor my local Python project.',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='calendar')),before)
            snap=PersonalOperationsService(store,connectors=m).snapshot(owner_user_id='alice');row=next(x for x in snap['intelligence']['connectors']['items'] if x['connector_id']=='calendar');self.assertEqual(row['status'],'HEALTHY');self.assertEqual(row['authorization_state'],'AUTHORIZED');self.assertNotIn('Private meeting',json.dumps(row));self.assertNotIn('Private Calendar',json.dumps(row))

    def test_model_routes_unchanged_and_calendar_not_a_model_route(self):
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(m.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
