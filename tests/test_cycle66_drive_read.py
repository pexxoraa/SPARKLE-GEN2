import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
import httplib2
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sparkle.secrets import SecretResolver
from sparkle_gen2.drive_connector import DRIVE_READONLY_SCOPE,DriveConnectorError,DriveCredentialSource,DriveReadAdapter
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
    def has_scopes(self,scopes):return list(scopes)==[DRIVE_READONLY_SCOPE]
    def refresh(self,_request):
        self.refresh_calls+=1
        if self.refresh_error:raise self.refresh_error
        self.expired=False;self.valid=True

class FakeSource:
    secret_ref='SPARKLE_DRIVE_TOKEN_FILE'
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

class AboutApi:
    def __init__(self,parent):self.parent=parent
    def get(self,**kwargs):self.parent.calls.append(('about_get',dict(kwargs)));return Req(self.parent.about_value,self.parent.about_error)

class FilesApi:
    def __init__(self,parent):self.parent=parent
    def list(self,**kwargs):self.parent.calls.append(('files_list',dict(kwargs)));return Req(self.parent.list_value,self.parent.list_error)
    def get(self,**kwargs):
        self.parent.calls.append(('files_get',dict(kwargs)));fid=kwargs['fileId'];value=self.parent.get_values.pop(0) if len(self.parent.get_values)>1 else self.parent.get_values[0];return Req(value,self.parent.get_error)

class FakeService:
    def __init__(self,*,files=None,file=None,permission_id='perm-user-1'):
        self.about_value={'user':{'permissionId':permission_id,'emailAddress':'private@example.invalid'}};self.about_error=None;self.list_value={'files':files if files is not None else [self.file()]};self.list_error=None;self.get_values=[file or self.file()];self.get_error=None;self.calls=[]
    @staticmethod
    def file(fid='fileABC123',name='Private Python.py',mime='text/x-python'):
        return {'id':fid,'name':name,'mimeType':mime,'modifiedTime':'2026-09-19T10:00:00Z','size':'321','trashed':False,'description':'PRIVATE-CONTENT-MUST-NOT-PERSIST','webContentLink':'https://private.invalid'}
    def about(self):return AboutApi(self)
    def files(self):return FilesApi(self)

class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        permission,risk=super().evaluate(capability,subject,scope,timestamp)
        if capability=='drive.read':permission.effect=PermissionEffect.DENY
        return permission,risk

class Cycle66DriveReadTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='drive')
    def manager(self,store=None,*,owner='alice',service=None,source=None,policy=None):
        source=source or FakeSource();service=service or FakeService();adapter=DriveReadAdapter(source,service_factory=lambda _c:service);auth=adapter.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=SecretResolver({}),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('drive',['drive.read'],owner_user_id=owner,actor='oauth-test',reference=auth['authorization_reference']);m.connect('drive',owner_user_id=owner);return m,adapter,service

    def test_registration_exact_google_drive_read_only(self):
        d=self.descriptor();self.assertEqual(d.provider_system,'Google Drive API');self.assertEqual(d.secret_refs,('SPARKLE_DRIVE_TOKEN_FILE',));ops={x.operation for x in d.capabilities};self.assertEqual(ops,{'list_files','get_file_metadata'});self.assertTrue(all(x.scope=='drive.read' and x.mode.value=='READ' and x.policy_capability=='drive.read' for x in d.capabilities));self.assertFalse({'create_file','upload_file','update_file','delete_file','move_file','rename_file','share','download'} & ops)

    def test_missing_credential_and_authorization_success(self):
        a=DriveReadAdapter(FakeSource(configured=False),service_factory=lambda _c:FakeService());h=a.health();self.assertFalse(h['ok']);self.assertEqual(h['authorization_state'],'NOT_CONFIGURED')
        m,_,_=self.manager();row=m.inspect('drive',owner_user_id='alice');self.assertTrue(row['configured']);self.assertTrue(row['authorized']);self.assertTrue(row['connected']);self.assertEqual(m.health('drive',owner_user_id='alice')['status'],'HEALTHY')

    def test_refresh_success_expired_revoked_refresh_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'token.json';p.write_text('{}');good=FakeCred(expired=True,valid=False);src=DriveCredentialSource(path=p,loader=lambda *_a,**_k:good,request_factory=lambda:object());self.assertIs(src.load(),good);self.assertEqual(good.refresh_calls,1)
            src=DriveCredentialSource(path=p,loader=lambda *_a,**_k:FakeCred(expired=True,valid=False,refresh_token=None))
            with self.assertRaises(DriveConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_EXPIRED')
            src=DriveCredentialSource(path=p,loader=lambda *_a,**_k:FakeCred(expired=True,valid=False,refresh_error=RefreshError('invalid_grant')),request_factory=lambda:object())
            with self.assertRaises(DriveConnectorError) as cm:src.load()
            self.assertEqual(cm.exception.category,'AUTH_REVOKED')

    def test_policy_allow_low_deny_and_revoked(self):
        p,r=PolicyEngine().evaluate('drive.read','alice','drive:list_files',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');m,_,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')
        m,_,_=self.manager();m.revoke('drive',owner_user_id='alice',actor='human')
        with self.assertRaises(PermissionError):m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')

    def test_list_files_bounded_query_fields_and_verification(self):
        files=[FakeService.file('fileABC123','A.py','text/x-python'),FakeService.file('fileDEF456','B.txt','text/plain')];service=FakeService(files=files,file=files[0]);m,_,_=self.manager(service=service);r=m.invoke_read('drive','list_files',{'max_results':2,'query':"name contains '.py'"},'drive.read',owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(value['result_count'],2);self.assertEqual(set(value['files'][0]),{'file_id','name','mime_type','modified_time','size_bytes'});call=next(x for x in service.calls if x[0]=='files_list');self.assertEqual(call[1]['pageSize'],2);self.assertEqual(call[1]['q'],"name contains '.py'");self.assertIn('files(id,name,mimeType,modifiedTime,size)',call[1]['fields']);self.assertTrue(r['verification']['verified']);self.assertEqual(r['verification']['file_count'],2)
        for invalid in (0,26,True,'2'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):m.invoke_read('drive','list_files',{'max_results':invalid},'drive.read',owner_user_id='alice')
        for query in ('', 'x'*513):
            with self.subTest(query_len=len(query)),self.assertRaises(ValueError):m.invoke_read('drive','list_files',{'query':query},'drive.read',owner_user_id='alice')

    def test_get_file_metadata_bounded_no_content_fields(self):
        file=FakeService.file();service=FakeService(file=file);service.get_values=[file,file];m,_,_=self.manager(service=service);r=m.invoke_read('drive','get_file_metadata',{'file_id':'fileABC123'},'drive.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');value=r['result']['result'];self.assertEqual(set(value),{'file_id','name','mime_type','modified_time','size_bytes','trashed'});self.assertNotIn('description',json.dumps(value));self.assertNotIn('webContentLink',json.dumps(value));calls=[x for x in service.calls if x[0]=='files_get'];self.assertTrue(calls);self.assertNotIn('content',calls[0][1].get('fields','').lower());self.assertTrue(r['verification']['metadata_sha256'])

    def test_malformed_ids_and_provider_responses_fail_closed(self):
        m,_,_=self.manager()
        for fid in ('','bad id','x'*1025,None):
            with self.subTest(fid=fid),self.assertRaises((ValueError,TypeError)):m.invoke_read('drive','get_file_metadata',{'file_id':fid},'drive.read',owner_user_id='alice')
        bad=[{'id':None,'name':'x','mimeType':'text/plain'},{'id':'fileABC123','name':5,'mimeType':'text/plain'},{'id':'fileABC123','name':'x','mimeType':''},{'id':'fileABC123','name':'x','mimeType':'text/plain','size':'not-number'}]
        for raw in bad:
            service=FakeService(files=[raw]);m,_,_=self.manager(service=service)
            with self.subTest(raw=raw),self.assertRaises((DriveConnectorError,ValueError)):m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')

    def test_wrong_account_identity_fails_verification(self):
        service=FakeService();m,adapter,_=self.manager(service=service);result=adapter.invoke('list_files',{'max_results':1});service.about_value={'user':{'permissionId':'other-user'}};evidence=adapter.verify('list_files',result);self.assertFalse(evidence['verified']);self.assertEqual(evidence['reason'],'authorized_account_identity_mismatch')

    def test_provider_errors_timeout_rate_limit_and_auth(self):
        service=FakeService();m,_,_=self.manager(service=service);service.list_error=RuntimeError('private provider details')
        with self.assertRaises(DriveConnectorError) as cm:m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'DRIVE_API_ERROR');self.assertNotIn('private provider details',json.dumps(m.invocations(owner_user_id='alice',connector_id='drive')[-1]))
        service=FakeService();m,_,_=self.manager(service=service);service.list_error=TimeoutError('slow')
        with self.assertRaises(DriveConnectorError) as cm:m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'TIMEOUT')
        for status,category in ((401,'AUTH_EXPIRED'),(403,'DRIVE_RATE_LIMIT'),(429,'DRIVE_RATE_LIMIT')):
            service=FakeService();m,_,_=self.manager(service=service);service.list_error=HttpError(httplib2.Response({'status':str(status)}),b'{}')
            with self.subTest(status=status),self.assertRaises(DriveConnectorError) as cm:m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice')
            self.assertEqual(cm.exception.category,category)

    def test_owner_isolation_restart_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g2.sqlite3';store=Gen2Store(path);m,_,_=self.manager(store);m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='drive')),1);self.assertEqual(m.invocations(owner_user_id='bob',connector_id='drive'),[])
            with self.assertRaises(PermissionError):m.invoke_read('drive','list_files',{},'drive.read',owner_user_id='bob')
            service=FakeService();adapter=DriveReadAdapter(FakeSource(),service_factory=lambda _c:service);adapter.authorize();m2=ConnectorManager(Gen2Store(path),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=adapter);self.assertEqual(m2.health('drive',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='drive')),1)

    def test_credential_content_and_private_names_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store);m.invoke_read('drive','get_file_metadata',{'file_id':'fileABC123'},'drive.read',owner_user_id='alice');raw=Path(store.path).read_bytes()
            for value in (b'access-secret-token',b'refresh-secret',b'client-secret',b'Authorization',b'PRIVATE-CONTENT-MUST-NOT-PERSIST',b'private@example.invalid',b'Private Python.py'):
                self.assertNotIn(value,raw)
            row=store.connector_invocations(owner_user_id='alice',connector_id='drive')[0];self.assertEqual(row['verification_status'],'VERIFIED');self.assertIn('metadata_sha256',row['verification']);self.assertNotIn('Private Python.py',json.dumps(row))

    def test_personalagent_read_path_no_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store,owner='user');proposal=PlanProposal(uuid.uuid4().hex,'drive',[PlanProposalStep('drive-read','List Drive files',['connector_read'],[],['verified Drive read'],{'connector_id':'drive','operation':'list_files','arguments':{'max_results':1},'classification':'PRIVATE'},30,0)],[{'description':'Drive verified','verification_method':'all_steps_verified'}],'LOW',.95,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);result=agent.start('Show me my recent Drive files.',user_id='user');self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['approvals'],[]);self.assertEqual(store.connector_invocations(owner_user_id='user',connector_id='drive')[0]['verification_status'],'VERIFIED')

    def test_context_minimization_operations_snapshot_and_model_routes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store);ctx=PersonalContextAssembler(connectors=m).gather('Show my recent Drive files.',owner_user_id='alice');self.assertTrue([x for x in ctx['items'] if x['source']=='drive']);before=len(m.invocations(owner_user_id='alice',connector_id='drive'));PersonalContextAssembler(connectors=m).gather('What meetings do I have tomorrow?',owner_user_id='alice');self.assertEqual(len(m.invocations(owner_user_id='alice',connector_id='drive')),before);snap=PersonalOperationsService(store,connectors=m).snapshot(owner_user_id='alice');row=next(x for x in snap['intelligence']['connectors']['items'] if x['connector_id']=='drive');self.assertEqual(row['status'],'HEALTHY');self.assertNotIn('Private Python.py',json.dumps(row))
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));mm=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(mm.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
