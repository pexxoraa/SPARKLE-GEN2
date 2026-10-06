import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlparse,parse_qs
from sparkle.secrets import SecretResolver
from sparkle_gen2.github_connector import GitHubConnectorError,GitHubCredentialSource,GitHubReadAdapter
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

class Resp:
    def __init__(self,value):self.raw=json.dumps(value).encode()
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n=-1):return self.raw if n<0 else self.raw[:n]

class FakeAPI:
    def __init__(self):
        self.calls=[];self.errors={};self.user={'id':1001,'login':'owner','type':'User','email':'private@example.invalid'}
        self.repo={'id':2001,'owner':{'login':'owner'},'name':'repo','full_name':'owner/repo','private':True,'updated_at':'2026-09-20T00:00:00Z','default_branch':'main','archived':False,'disabled':False,'description':'PRIVATE REPO DESC'}
        self.content={'path':'README.md','name':'README.md','type':'file','size':12,'sha':'a'*40,'content':'PRIVATE SOURCE CONTENT'}
        self.issue={'id':3001,'number':7,'state':'open','title':'Private issue title','updated_at':'2026-09-20T00:00:00Z','body':'PRIVATE ISSUE BODY'}
        self.pr={'id':4001,'number':8,'state':'open','title':'Private PR title','updated_at':'2026-09-20T00:00:00Z','draft':False,'body':'PRIVATE PR BODY'}
        self.workflow={'id':5001,'name':'CI','path':'.github/workflows/ci.yml','state':'active'}
    def __call__(self,req,timeout=20):
        u=urlparse(req.full_url);path=u.path;query=parse_qs(u.query);self.calls.append((path,query,dict(req.header_items())))
        if path in self.errors:
            code=self.errors[path];raise HTTPError(req.full_url,code,'error',{},None)
        if path=='/user':return Resp(self.user)
        if path=='/user/repos':return Resp([self.repo])
        if path=='/repos/owner/repo':return Resp(self.repo)
        if path=='/repos/owner/repo/contents':return Resp([self.content])
        if path=='/repos/owner/repo/git/trees/main':return Resp({'tree':[{'path':'README.md','type':'blob','sha':'a'*40,'size':12},{'path':'src','type':'tree','sha':'b'*40}]})
        if path=='/repos/owner/repo/git/trees/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb':return Resp({'tree':[{'path':'main.py','type':'blob','sha':'c'*40,'size':10}]})
        if path=='/repos/owner/repo/contents/src':return Resp([{'path':'src/main.py','name':'main.py','type':'file','size':10,'sha':'c'*40,'content':'PRIVATE NESTED SOURCE'}])
        if path=='/repos/owner/repo/issues':return Resp([self.issue])
        if path=='/repos/owner/repo/issues/7':return Resp(self.issue)
        if path=='/repos/owner/repo/pulls':return Resp([self.pr])
        if path=='/repos/owner/repo/pulls/8':return Resp(self.pr)
        if path=='/repos/owner/repo/actions/workflows':return Resp({'total_count':1,'workflows':[self.workflow]})
        if path=='/repos/owner/repo/actions/workflows/5001':return Resp(self.workflow)
        raise AssertionError(path)

class Source:
    secret_ref='SPARKLE_GITHUB_TOKEN_FILE'
    def __init__(self,configured=True,token='secret-github-pat'):self.value=configured;self.token=token
    def configured(self):return self.value
    def load(self):
        if not self.value:raise GitHubConnectorError('AUTH_REQUIRED','missing')
        return self.token

class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        p,r=super().evaluate(capability,subject,scope,timestamp)
        if capability=='github.read':p.effect=PermissionEffect.DENY
        return p,r

class Cycle67GitHubReadTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='github')
    def manager(self,store=None,*,owner='alice',api=None,source=None,policy=None):
        api=api or FakeAPI();source=source or Source();adapter=GitHubReadAdapter(source,opener=api);auth=adapter.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),secrets=SecretResolver({}),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('github',['github.read'],owner_user_id=owner,actor='pat-test',reference=auth['authorization_reference']);m.connect('github',owner_user_id=owner);return m,adapter,api

    def test_exact_descriptor_read_only(self):
        d=self.descriptor();self.assertEqual(d.provider_system,'GitHub API');self.assertEqual(d.secret_refs,('SPARKLE_GITHUB_TOKEN_FILE',));ops={x.operation for x in d.capabilities};self.assertEqual(ops,{'get_user','list_repositories','get_repository','list_repository_contents','list_issues','list_pull_requests','list_workflows'});self.assertTrue(all(x.scope=='github.read' and x.mode.value=='READ' and x.policy_capability=='github.read' for x in d.capabilities));self.assertFalse({'create_issue','comment','merge_pull_request','create_pull_request','push','commit','create_branch','delete_branch','workflow_dispatch'} & ops)

    def test_credential_missing_authorized_and_revoked(self):
        a=GitHubReadAdapter(Source(False),opener=FakeAPI());h=a.health();self.assertEqual(h['authorization_state'],'NOT_CONFIGURED')
        m,_,_=self.manager();self.assertEqual(m.health('github',owner_user_id='alice')['status'],'HEALTHY')
        api=FakeAPI();api.errors['/user']=401;a=GitHubReadAdapter(Source(),opener=api);h=a.health();self.assertEqual(h['authorization_state'],'REVOKED');self.assertEqual(h['status'],'AUTH_REVOKED')

    def test_real_credential_source_reads_only_symbolic_path(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'token.json';p.write_text(json.dumps({'token':'test-token'}));p.chmod(0o600);src=GitHubCredentialSource(path=p);self.assertTrue(src.configured());self.assertEqual(src.load(),'test-token')
            p.write_text('{}')
            with self.assertRaises(GitHubConnectorError):src.load()

    def test_policy_allow_low_and_deny(self):
        p,r=PolicyEngine().evaluate('github.read','alice','github:list_repositories',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);self.assertEqual(r.level.value,'LOW');m,_,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='alice')

    def test_user_and_repository_listing_bounded_headers_and_query(self):
        m,_,api=self.manager();u=m.invoke_read('github','get_user',{},'github.read',owner_user_id='alice');self.assertEqual(u['status'],'VERIFIED');self.assertEqual(set(u['result']['result']),{'user_id','login','account_type'});r=m.invoke_read('github','list_repositories',{'max_results':10,'query':'repo'},'github.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertEqual(r['result']['result']['result_count'],1);call=next(x for x in api.calls if x[0]=='/user/repos');self.assertEqual(call[1]['per_page'],['10']);headers={k.lower():v for k,v in call[2].items()};self.assertEqual(headers['accept'],'application/vnd.github+json');self.assertEqual(headers['x-github-api-version'],'2022-11-28');self.assertIn('authorization',headers)
        for v in (0,26,True,'5'):
            with self.subTest(v=v),self.assertRaises(ValueError):m.invoke_read('github','list_repositories',{'max_results':v},'github.read',owner_user_id='alice')
        with self.assertRaises(ValueError):m.invoke_read('github','list_repositories',{'query':'x'*257},'github.read',owner_user_id='alice')

    def test_repository_metadata_exact_reread(self):
        m,_,_=self.manager();r=m.invoke_read('github','get_repository',{'owner':'owner','repo':'repo'},'github.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertTrue(r['verification']['metadata_sha256']);self.assertNotIn('description',json.dumps(r['result']['result']))

    def test_contents_metadata_tree_reread_no_content(self):
        m,_,_=self.manager();r=m.invoke_read('github','list_repository_contents',{'owner':'owner','repo':'repo','max_results':20},'github.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');item=r['result']['result']['items'][0];self.assertEqual(set(item),{'path','name','content_type','size_bytes','sha'});self.assertNotIn('PRIVATE SOURCE CONTENT',json.dumps(r));self.assertEqual(r['verification']['result_count'],1)

    def test_nested_contents_verify_via_tree_without_content_download(self):
        m,_,_=self.manager();r=m.invoke_read('github','list_repository_contents',{'owner':'owner','repo':'repo','path':'src','max_results':20},'github.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertEqual(r['result']['result']['result_count'],1);self.assertNotIn('PRIVATE NESTED SOURCE',json.dumps(r))

    def test_issue_pr_workflow_lists_independently_reread(self):
        m,_,_=self.manager()
        cases=[('list_issues','issues'),('list_pull_requests','pull_requests'),('list_workflows','workflows')]
        for op,key in cases:
            with self.subTest(op=op):
                r=m.invoke_read('github',op,{'owner':'owner','repo':'repo','max_results':10},'github.read',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');self.assertEqual(r['result']['result']['result_count'],1);self.assertTrue(r['verification']['item_id_hashes']);self.assertNotIn('PRIVATE ISSUE BODY',json.dumps(r));self.assertNotIn('PRIVATE PR BODY',json.dumps(r))

    def test_malformed_provider_data_and_ids(self):
        m,_,_=self.manager()
        for args in ({'owner':'bad owner','repo':'repo'},{'owner':'owner','repo':'bad/repo'}):
            with self.subTest(args=args),self.assertRaises(ValueError):m.invoke_read('github','get_repository',args,'github.read',owner_user_id='alice')
        api=FakeAPI();api.repo=dict(api.repo);api.repo['id']='bad';m,_,_=self.manager(api=api)
        with self.assertRaises(GitHubConnectorError):m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='alice')

    def test_wrong_account_verification_fails(self):
        api=FakeAPI();m,a,_=self.manager(api=api);result=a.invoke('list_repositories',{});api.user={'id':9999,'login':'other','type':'User'};ev=a.verify('list_repositories',result);self.assertFalse(ev['verified']);self.assertEqual(ev['reason'],'authorized_account_identity_mismatch')

    def test_http_errors_and_timeout(self):
        for code,cat in ((401,'AUTH_REVOKED'),(403,'GITHUB_FORBIDDEN'),(404,'GITHUB_NOT_FOUND'),(429,'GITHUB_RATE_LIMIT')):
            api=FakeAPI();m,_,_=self.manager(api=api);api.errors['/user/repos']=code
            with self.subTest(code=code),self.assertRaises(GitHubConnectorError) as cm:m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='alice')
            self.assertEqual(cm.exception.category,cat)
        class TimeoutAPI(FakeAPI):
            def __call__(self,req,timeout=20):
                if urlparse(req.full_url).path=='/user/repos':raise TimeoutError('slow')
                return super().__call__(req,timeout)
        m,_,_=self.manager(api=TimeoutAPI())
        with self.assertRaises(GitHubConnectorError) as cm:m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='alice')
        self.assertEqual(cm.exception.category,'TIMEOUT')

    def test_owner_restart_persistence_and_secret_nonpersistence(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store);m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='alice');self.assertEqual(m.invocations(owner_user_id='bob',connector_id='github'),[])
            with self.assertRaises(PermissionError):m.invoke_read('github','list_repositories',{},'github.read',owner_user_id='bob')
            raw=Path(store.path).read_bytes();self.assertNotIn(b'secret-github-pat',raw);self.assertNotIn(b'PRIVATE REPO DESC',raw);self.assertNotIn(b'PRIVATE SOURCE CONTENT',raw)
            api=FakeAPI();adapter=GitHubReadAdapter(Source(),opener=api);adapter.authorize();m2=ConnectorManager(Gen2Store(Path(d)/'g2.sqlite3'),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=adapter);self.assertEqual(m2.health('github',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='github')),1)

    def test_personalagent_context_operations_and_existing_connectors_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,_,_=self.manager(store,owner='user');proposal=PlanProposal(uuid.uuid4().hex,'github',[PlanProposalStep('gh','List repos',['connector_read'],[],['verified GitHub read'],{'connector_id':'github','operation':'list_repositories','arguments':{'max_results':1},'classification':'PRIVATE'},30,0)],[{'description':'GitHub verified','verification_method':'all_steps_verified'}],'LOW',.95,[],now());g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}));agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);res=agent.start('Show my GitHub repositories.',user_id='user');self.assertEqual(res['status'],'COMPLETED');self.assertEqual(res['approvals'],[])
            ctx=PersonalContextAssembler(connectors=m).gather('Show my GitHub repositories.',owner_user_id='user');self.assertTrue([x for x in ctx['items'] if x['source']=='github']);before=len(m.invocations(owner_user_id='user',connector_id='github'));PersonalContextAssembler(connectors=m).gather('What meetings do I have tomorrow?',owner_user_id='user');self.assertEqual(len(m.invocations(owner_user_id='user',connector_id='github')),before)
            snap=PersonalOperationsService(store,connectors=m).snapshot(owner_user_id='user');row=next(x for x in snap['intelligence']['connectors']['items'] if x['connector_id']=='github');self.assertEqual(row['status'],'HEALTHY');self.assertNotIn('Private issue title',json.dumps(row));self.assertNotIn('Private PR title',json.dumps(row));self.assertNotIn('PRIVATE SOURCE CONTENT',json.dumps(row))
        desc={x.connector_id:{c.operation for c in x.capabilities} for x in DESCRIPTORS};self.assertEqual(desc['gmail'],{'list_messages','get_message_metadata'});self.assertEqual(desc['calendar'],{'list_calendars','list_events','get_event'});self.assertEqual(desc['drive'],{'list_files','get_file_metadata'})

    def test_model_routes_unchanged(self):
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));m=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(m.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
