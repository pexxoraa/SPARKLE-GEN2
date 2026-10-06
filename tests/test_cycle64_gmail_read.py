import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
import httplib2
from sparkle.secrets import SecretResolver
from sparkle_gen2.connector_catalog import DESCRIPTORS
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.context_sources import PersonalContextAssembler
from sparkle_gen2.dashboard import PersonalOperationsService
from sparkle_gen2.core_time import now
from sparkle_gen2.gmail_connector import (DEFAULT_HEADERS,GMAIL_READONLY_SCOPE,GmailConnectorError,GmailCredentialSource,GmailReadAdapter)
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class FakeCred:
    def __init__(self,*,expired=False,valid=True,refresh_token='refresh-secret',refresh_error=None):self.expired=expired;self.valid=valid;self.refresh_token=refresh_token;self.refresh_error=refresh_error;self.refresh_calls=0
    def has_scopes(self,scopes):return list(scopes)==[GMAIL_READONLY_SCOPE]
    def refresh(self,request):
        self.refresh_calls+=1
        if self.refresh_error:raise self.refresh_error
        self.expired=False;self.valid=True

class FakeSource:
    secret_ref='SPARKLE_GMAIL_TOKEN_FILE'
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

class FakeMessages:
    def __init__(self,parent):self.parent=parent
    def list(self,**kwargs):self.parent.calls.append(('list',dict(kwargs)));return Req(self.parent.list_value,self.parent.list_error)
    def get(self,**kwargs):
        self.parent.calls.append(('get',dict(kwargs)));value=self.parent.get_values.pop(0) if len(self.parent.get_values)>1 else self.parent.get_values[0];return Req(value,self.parent.get_error)

class FakeUsers:
    def __init__(self,parent):self.parent=parent
    def getProfile(self,**kwargs):
        self.parent.calls.append(('profile',dict(kwargs)));value=self.parent.profile_values.pop(0) if len(self.parent.profile_values)>1 else self.parent.profile_values[0];return Req(value,self.parent.profile_error)
    def messages(self):return FakeMessages(self.parent)

class FakeService:
    def __init__(self,*,email='person@example.invalid',messages=None,metadata=None):
        self.profile_values=[{'emailAddress':email}];self.list_value={'messages':messages if messages is not None else [{'id':'abc123','threadId':'thr123'}]};self.get_values=[metadata or self.metadata('abc123','thr123')];self.calls=[];self.list_error=None;self.get_error=None;self.profile_error=None
    @staticmethod
    def metadata(mid='abc123',tid='thr123'):
        return {'id':mid,'threadId':tid,'labelIds':['INBOX','UNREAD'],'internalDate':'1700000000000','snippet':'private snippet','payload':{'headers':[{'name':'From','value':'sender@example.invalid'},{'name':'To','value':'person@example.invalid'},{'name':'Subject','value':'Private subject'},{'name':'Date','value':'Mon, 1 Jan 2026 00:00:00 +0000'}],'body':{'data':'FULL-BODY-MUST-NOT-ESCAPE'}}}
    def users(self):return FakeUsers(self)

class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        permission,risk=super().evaluate(capability,subject,scope,timestamp)
        if capability=='gmail.read':permission.effect=PermissionEffect.DENY
        return permission,risk

class Cycle64GmailReadTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='gmail')
    def manager(self,store=None,*,owner='alice',service=None,source=None,policy=None):
        source=source or FakeSource();service=service or FakeService();adapter=GmailReadAdapter(source,service_factory=lambda _c:service);auth=adapter.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=SecretResolver({}),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('gmail',['gmail.read'],owner_user_id=owner,actor='oauth-test',reference=auth['authorization_reference']);m.connect('gmail',owner_user_id=owner);return m,adapter,service

    def test_registration_is_read_only_google_gmail(self):
        d=self.descriptor();self.assertEqual(d.provider_system,'Google Gmail API');self.assertEqual(d.secret_refs,('SPARKLE_GMAIL_TOKEN_FILE',));ops={x.operation for x in d.capabilities};self.assertEqual(ops,{'list_messages','get_message_metadata'});self.assertTrue(all(x.scope=='gmail.read' and x.mode.value=='READ' and x.policy_capability=='gmail.read' for x in d.capabilities));self.assertFalse({'draft','send','delete','modify'} & ops)

    def test_missing_credential_and_valid_authorization_reference(self):
        a=GmailReadAdapter(FakeSource(configured=False),service_factory=lambda _c:FakeService());h=a.health();self.assertFalse(h['ok']);self.assertEqual(h['authorization_state'],'NOT_CONFIGURED')
        m,a,_=self.manager();row=m.inspect('gmail',owner_user_id='alice');self.assertTrue(row['configured']);self.assertTrue(row['authorized']);self.assertTrue(row['connected']);self.assertEqual(m.health('gmail',owner_user_id='alice')['status'],'HEALTHY');self.assertTrue(m.authorization_required('gmail',owner_user_id='alice')['granted_scopes']==['gmail.read'])

    def test_credential_source_refresh_success_expired_without_refresh_and_refresh_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'token.json';p.write_text('{}')
            good=FakeCred(expired=True,valid=False);src=GmailCredentialSource(path=p,loader=lambda *_a,**_k:good,request_factory=lambda:object());self.assertIs(src.load(),good);self.assertEqual(good.refresh_calls,1);self.assertTrue(good.valid)
            no_refresh=FakeCred(expired=True,valid=False,refresh_token=None);src=GmailCredentialSource(path=p,loader=lambda *_a,**_k:no_refresh)
            with self.assertRaises(GmailConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_EXPIRED')
            revoked=FakeCred(expired=True,valid=False,refresh_error=RefreshError('invalid_grant'));src=GmailCredentialSource(path=p,loader=lambda *_a,**_k:revoked,request_factory=lambda:object())
            with self.assertRaises(GmailConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_REVOKED')

    def test_revoked_authorization_is_owner_scoped_and_fails_closed(self):
        m,_,_=self.manager();m.revoke('gmail',owner_user_id='alice',actor='human');self.assertEqual(m.health('gmail',owner_user_id='alice')['status'],'REVOKED')
        with self.assertRaises(PermissionError):m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')
        self.assertFalse(m.inspect('gmail',owner_user_id='bob')['authorized'])

    def test_policy_read_is_allow_low_and_deny_is_respected(self):
        p,r=PolicyEngine().evaluate('gmail.read','alice','gmail:list_messages',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW')
        m,_,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')

    def test_list_messages_is_bounded_and_verified(self):
        service=FakeService(messages=[{'id':'a1','threadId':'t1'},{'id':'a2','threadId':'t2'}]);service.get_values=[FakeService.metadata('a1','t1')];m,_,_=self.manager(service=service);r=m.invoke_read('gmail','list_messages',{'max_results':2},'gmail.read',owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(value['result_count'],2);self.assertEqual(set(value['messages'][0]),{'message_id','thread_id'});self.assertTrue(r['verification']['verified']);self.assertEqual(r['verification']['message_count'],2);self.assertEqual(m.invocations(owner_user_id='alice',connector_id='gmail')[-1]['external_reference'],'gmail:users.messages.list');list_call=next(x for x in service.calls if x[0]=='list');self.assertEqual(list_call[1]['userId'],'me');self.assertEqual(list_call[1]['maxResults'],2)
        for invalid in (0,26,True,'2'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):m.invoke_read('gmail','list_messages',{'max_results':invalid},'gmail.read',owner_user_id='alice')

    def test_optional_query_is_controlled_and_bounded(self):
        m,_,service=self.manager();m.invoke_read('gmail','list_messages',{'max_results':1,'query':'is:unread'},'gmail.read',owner_user_id='alice');call=next(x for x in service.calls if x[0]=='list');self.assertEqual(call[1]['q'],'is:unread')
        for q in ('','x'*513,3):
            with self.subTest(q=str(q)[:8]),self.assertRaises(ValueError):m.invoke_read('gmail','list_messages',{'query':q},'gmail.read',owner_user_id='alice')

    def test_metadata_is_bounded_structured_and_verified_without_body(self):
        metadata=FakeService.metadata();service=FakeService(metadata=metadata);service.get_values=[metadata,metadata];m,_,_=self.manager(service=service);r=m.invoke_read('gmail','get_message_metadata',{'message_id':'abc123','headers':list(DEFAULT_HEADERS)},'gmail.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(value['message_id'],'abc123');self.assertEqual(value['thread_id'],'thr123');self.assertEqual(len(value['label_ids']),2);self.assertEqual(len(value['headers']),4);self.assertIsNone(value['snippet']);self.assertNotIn('body',json.dumps(value).lower());self.assertNotIn('FULL-BODY-MUST-NOT-ESCAPE',json.dumps(r));self.assertEqual(r['verification']['header_count'],4)

    def test_metadata_validation_rejects_bad_id_thread_labels_and_missing_headers(self):
        bad=[
            {'id':None,'threadId':'t','labelIds':[],'payload':{'headers':[]}},
            {'id':'a','threadId':None,'labelIds':[],'payload':{'headers':[]}},
            {'id':'a','threadId':'t','labelIds':'INBOX','payload':{'headers':[]}},
            {'id':'a','threadId':'t','labelIds':[],'payload':{'headers':[{'name':'From','value':'x'}]}},
        ]
        for raw in bad:
            service=FakeService();service.get_values=[raw];m,_,_=self.manager(service=service)
            with self.subTest(raw=raw),self.assertRaises((GmailConnectorError,ValueError)):m.invoke_read('gmail','get_message_metadata',{'message_id':'a'},'gmail.read',owner_user_id='alice')
        m,_,_=self.manager()
        with self.assertRaises(ValueError):m.invoke_read('gmail','get_message_metadata',{'message_id':'../bad'},'gmail.read',owner_user_id='alice')

    def test_wrong_account_identity_fails_verification(self):
        service=FakeService();m,adapter,_=self.manager(service=service);service.profile_values=[{'emailAddress':'different@example.invalid'}];result=adapter.invoke('list_messages',{'max_results':1});evidence=adapter.verify('list_messages',result);self.assertFalse(evidence['verified']);self.assertEqual(evidence['reason'],'authorized_account_identity_mismatch')

    def test_provider_failure_timeout_and_malformed_response_are_not_success(self):
        service=FakeService();m,_,_=self.manager(service=service);service.list_error=RuntimeError('provider details must not escape')
        with self.assertRaises(GmailConnectorError) as cm:m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'GMAIL_API_ERROR');row=m.invocations(owner_user_id='alice',connector_id='gmail')[-1];self.assertEqual(row['status'],'FAILED');self.assertEqual(row['failure']['category'],'GMAIL_API_ERROR');self.assertNotIn('provider details',json.dumps(row))
        service=FakeService();m,_,_=self.manager(service=service);service.list_error=TimeoutError('slow')
        with self.assertRaises(GmailConnectorError) as cm:m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'TIMEOUT')
        service=FakeService();service.list_value={'messages':[{}]};m,_,_=self.manager(service=service)
        with self.assertRaises((GmailConnectorError,ValueError)):m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')

    def test_no_credential_or_body_material_persists(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');service=FakeService();m,_,_=self.manager(store,service=service);m.invoke_read('gmail','get_message_metadata',{'message_id':'abc123'},'gmail.read',owner_user_id='alice');raw=Path(store.path).read_bytes();
            for secret in (b'access-secret-token',b'refresh-secret',b'client-secret',b'Authorization',b'FULL-BODY-MUST-NOT-ESCAPE',b'Private subject',b'sender@example.invalid'):
                self.assertNotIn(secret,raw)
            row=store.connector_invocations(owner_user_id='alice',connector_id='gmail')[0];self.assertEqual(row['verification_status'],'VERIFIED');self.assertIn('metadata_sha256',row['verification']);self.assertNotIn('Private subject',json.dumps(row));self.assertNotIn('sender@example.invalid',json.dumps(row))

    def test_owner_isolation_and_unauthorized_owner_rejected(self):
        m,_,_=self.manager(owner='alice');m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='gmail')),1);self.assertEqual(m.invocations(owner_user_id='bob',connector_id='gmail'),[])
        with self.assertRaises(PermissionError):m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='bob')

    def test_restart_retains_state_history_but_rechecks_health(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g2.sqlite3';store=Gen2Store(path);m,_,_=self.manager(store);m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice');self.assertEqual(m.health('gmail',owner_user_id='alice')['status'],'HEALTHY')
            service2=FakeService();adapter2=GmailReadAdapter(FakeSource(),service_factory=lambda _c:service2);adapter2.authorize();m2=ConnectorManager(Gen2Store(path),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=adapter2);self.assertEqual(m2.health('gmail',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='gmail')),1)

    def test_personalagent_read_path_is_no_approval_and_persists_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store,owner='user');proposal=PlanProposal(uuid.uuid4().hex,'email',[PlanProposalStep('gmail-read','List recent Gmail messages',['connector_read'],[],['verified Gmail read'],{'connector_id':'gmail','operation':'list_messages','arguments':{'max_results':1},'classification':'PRIVATE'},30,0)],[{'description':'Gmail result verified','verification_method':'all_steps_verified'}],'LOW',.95,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);result=agent.start('Check my recent emails.',user_id='user');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['approvals'],[]);rows=store.connector_invocations(owner_user_id='user',connector_id='gmail');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['verification_status'],'VERIFIED');self.assertEqual(rows[0]['goal_id'],result['goal_id'])

    def test_authorization_expiry_and_refresh_failure_propagate_to_manager_health(self):
        for category,expected in (('AUTH_EXPIRED','EXPIRED'),('AUTH_REVOKED','REVOKED')):
            source=FakeSource(error=GmailConnectorError(category,'safe'));adapter=GmailReadAdapter(source,service_factory=lambda _c:FakeService());m=ConnectorManager(policy=PolicyEngine(),default_owner='alice');m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('gmail',['gmail.read'],owner_user_id='alice',actor='prior-oauth',reference='gmail-account:opaque');h=m.health('gmail',owner_user_id='alice');self.assertEqual(h['authorization_state'],expected);self.assertFalse(h['health']=='HEALTHY')

    def test_rate_limit_and_auth_http_errors_are_classified(self):
        for status,category in ((429,'GMAIL_RATE_LIMIT'),(401,'AUTH_EXPIRED')):
            service=FakeService();m,_,_=self.manager(service=service);service.list_error=HttpError(httplib2.Response({'status':str(status)}),b'{}')
            with self.subTest(status=status),self.assertRaises(GmailConnectorError) as cm:m.invoke_read('gmail','list_messages',{'max_results':1},'gmail.read',owner_user_id='alice')
            self.assertEqual(cm.exception.category,category);self.assertEqual(m.invocations(owner_user_id='alice',connector_id='gmail')[-1]['failure']['category'],category)

    def test_context_fetches_only_bounded_gmail_for_email_related_goal(self):
        m,_,_=self.manager();ctx=PersonalContextAssembler(connectors=m).gather('Check my recent email.',owner_user_id='alice');gmail=[x for x in ctx['items'] if x['source']=='gmail'];self.assertTrue(gmail);self.assertLessEqual(len(gmail),1);self.assertNotIn('FULL-BODY-MUST-NOT-ESCAPE',json.dumps(ctx))
        before=len(m.invocations(owner_user_id='alice',connector_id='gmail'));PersonalContextAssembler(connectors=m).gather('Plan my local project.',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='gmail')),before)

    def test_operations_snapshot_exposes_health_not_mail_content(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store);snap=PersonalOperationsService(store,connectors=m).snapshot(owner_user_id='alice');rows=snap['intelligence']['connectors']['items'];gmail=next(x for x in rows if x['connector_id']=='gmail');self.assertEqual(gmail['status'],'HEALTHY');self.assertEqual(gmail['authorization_state'],'AUTHORIZED');text=json.dumps(gmail);self.assertNotIn('sender@example.invalid',text);self.assertNotIn('Private subject',text)

    def test_model_routes_unchanged_and_gmail_is_not_model_route(self):
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(m.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
