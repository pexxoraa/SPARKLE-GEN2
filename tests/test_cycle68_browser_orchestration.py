import json,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from sparkle_gen2.browser_orchestration import BrowserOrchestrator,BrowserScreenshotReference,MAX_LINKS,MAX_TEXT_CHARS
from sparkle_gen2.connector_catalog import DESCRIPTORS
from sparkle_gen2.connectors import ConnectorManager
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.gen1_interactions import Gen1BrowserSession
from sparkle_gen2.model_manager import ModelCapabilityManager,build_gen2_model_registry
from sparkle_gen2.models import ApprovalStatus,PermissionEffect,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store
from sparkle.secrets import SecretResolver

class FakeService:
    def __init__(self):self.rev=1;self.events=[];self.closed=False;self.last_allowed=[];self.timeout=False;self.escape=False
    def status(self):return {'browser':'configured','browser_accepted':True,'live_browser_verified':True}
    def browser_acceptance(self):return {'verified':True,'record_id':'accepted-browser-record'}
    def start_session(self,mode,**kwargs):self.rev=1;self.last_allowed=list(kwargs.get('allowed_hosts') or []);return {'id':'session-1234567890abcdef','mode':mode,'status':'active','revision':1,'allowed_hosts':self.last_allowed}
    def session(self,sid):return {'id':sid,'mode':'browser','status':'closed' if self.closed else 'active','revision':self.rev,'allowed_hosts':self.last_allowed}
    def browse_session(self,sid,url,expected_revision,timeout_seconds=15,max_text_chars=10000):
        if self.timeout:raise TimeoutError('timeout')
        if expected_revision!=self.rev:raise RuntimeError('revision conflict')
        self.rev+=1;final='https://evil.example/' if self.escape else url
        text=('Visible text '+('https://example.com/docs ' * 40)).strip()[:max_text_chars]
        out={'final_url':final,'title':'Example','text':text,'status_code':200,'session_revision':self.rev};self.events.append({'id':len(self.events)+1,'event':'browse','request':{'url':url},'result':out});return out
    def history(self,sid,limit=1):return self.events[-limit:]
    def close_session(self,sid,expected_revision):
        if expected_revision!=self.rev:raise RuntimeError('revision conflict')
        self.rev+=1;self.closed=True;return {'id':sid,'mode':'browser','status':'closed','revision':self.rev}
class FakeGen1:
    def __init__(self,service=None):self.system=SimpleNamespace(interactions=service or FakeService())
class EnvWrap:
    def __init__(self,base):self.base=base

class DenyPolicy(PolicyEngine):
    def evaluate(self,capability,subject,scope,timestamp):
        p,r=super().evaluate(capability,subject,scope,timestamp)
        if capability=='browser.navigate':p.effect=PermissionEffect.DENY
        return p,r
class Approval:
    def __init__(self,goal='g',task='t'):self.status=ApprovalStatus.APPROVED;self.goal_id=goal;self.task_run_id=task;self.approval_id='approval-1'

class Cycle68BrowserOrchestrationTests(unittest.TestCase):
    def descriptor(self):return next(x for x in DESCRIPTORS if x.connector_id=='browser')
    def manager(self,store=None,*,owner='alice',service=None,policy=None):
        service=service or FakeService();adapter=BrowserOrchestrator(EnvWrap(FakeGen1(service)),owner_user_id=owner);auth=adapter.authorize();m=ConnectorManager(store,policy=policy or PolicyEngine(),default_owner=owner);m.register_descriptor(self.descriptor(),adapter=adapter);m.authorize('browser',['browser.navigate','browser.read','browser.interact'],owner_user_id=owner,actor='test',reference=auth['authorization_reference']);m.connect('browser',owner_user_id=owner);return m,adapter,service

    def test_reuses_gen1_browser_session_and_no_second_browser_stack(self):
        g=FakeGen1();a=BrowserOrchestrator(g,owner_user_id='alice');self.assertTrue(a.configured());a.authorize();a.invoke_with_context('navigate',{'url':'https://example.com'},owner_user_id='alice');self.assertIsInstance(a._session,Gen1BrowserSession)
        source=Path('src/sparkle_gen2/browser_orchestration.py').read_text().lower();self.assertNotIn('playwright',source);self.assertNotIn('selenium',source);self.assertNotIn('webdriver',source)

    def test_descriptor_classification_exact(self):
        d=self.descriptor();caps={x.operation:x for x in d.capabilities};self.assertEqual(set(caps),{'navigate','read','interact'});self.assertEqual(caps['navigate'].mode.value,'READ');self.assertEqual(caps['read'].mode.value,'READ');self.assertEqual(caps['interact'].mode.value,'CONTROL');self.assertEqual(caps['navigate'].policy_capability,'browser.navigate');self.assertEqual(caps['interact'].policy_capability,'browser.interact')

    def test_navigation_read_bounds_and_links(self):
        m,a,_=self.manager();r=m.invoke_read('browser','navigate',{'url':'example.com'},'browser.navigate',owner_user_id='alice');self.assertEqual(r['status'],'VERIFIED');obs=r['result']['result']['observation'];self.assertTrue(obs['final_url'].startswith('https://'));self.assertLessEqual(len(obs['visible_text']),MAX_TEXT_CHARS);self.assertLessEqual(len(obs['links']),MAX_LINKS);self.assertTrue(obs['links']);rr=m.invoke_read('browser','read',{},'browser.read',owner_user_id='alice');self.assertEqual(rr['status'],'VERIFIED');self.assertEqual(rr['result']['result']['final_url'],obs['final_url'])

    def test_https_malformed_allowlist_and_redirect_escape(self):
        m,a,_=self.manager()
        for url in ('http://example.com','ftp://example.com','https://user:pass@example.com','https://example.com:444/'):
            with self.subTest(url=url),self.assertRaises(ValueError):m.invoke_read('browser','navigate',{'url':url},'browser.navigate',owner_user_id='alice')
        m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')
        with self.assertRaises(PermissionError):m.invoke_read('browser','navigate',{'url':'https://www.iana.org'},'browser.navigate',owner_user_id='alice')
        m2,a2,s2=self.manager();s2.escape=True
        with self.assertRaises(Exception):m2.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')

    def test_timeout_and_verification_failure(self):
        service=FakeService();m,_,_=self.manager(service=service);service.timeout=True
        with self.assertRaises(Exception) as cm:m.invoke_read('browser','navigate',{'url':'https://example.com','timeout_seconds':1},'browser.navigate',owner_user_id='alice')
        self.assertIn('TIMEOUT',getattr(cm.exception,'category','TIMEOUT'))
        m,a,s=self.manager();result=a.invoke_with_context('navigate',{'url':'https://example.com'},owner_user_id='alice');s.events[-1]['result']['status_code']=500;ev=a.verify_with_context('navigate',result,owner_user_id='alice');self.assertFalse(ev['verified'])

    def test_control_requires_approval_and_model_cannot_self_approve(self):
        m,a,_=self.manager();m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')
        target=a._last.links[0].url
        with self.assertRaises(PermissionError):m.invoke('browser','interact',{'action':'open_link','target_url':target},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t')
        with self.assertRaises(PermissionError):m.invoke('browser','interact',{'action':'open_link','target_url':target,'approved':True},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t')
        r=m.invoke('browser','interact',{'action':'open_link','target_url':target},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(r['status'],'VERIFIED')

    def test_side_effecting_interactions_are_not_allowlisted(self):
        m,a,_=self.manager();m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')
        for action in ('submit_form','type_text','purchase','send_message','delete','accept_invitation'):
            with self.subTest(action=action),self.assertRaises(PermissionError):m.invoke('browser','interact',{'action':action},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())

    def test_back_forward_reload_are_bounded_control(self):
        m,a,_=self.manager();m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice');target=a._last.links[0].url;m.invoke('browser','interact',{'action':'open_link','target_url':target},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval());self.assertEqual(m.invoke('browser','interact',{'action':'back'},'browser.interact',owner_user_id='alice',goal_id='g2',task_run_id='t2',approval=Approval('g2','t2'))['status'],'VERIFIED');self.assertEqual(m.invoke('browser','interact',{'action':'forward'},'browser.interact',owner_user_id='alice',goal_id='g3',task_run_id='t3',approval=Approval('g3','t3'))['status'],'VERIFIED');self.assertEqual(m.invoke('browser','interact',{'action':'reload'},'browser.interact',owner_user_id='alice',goal_id='g4',task_run_id='t4',approval=Approval('g4','t4'))['status'],'VERIFIED')

    def test_policy_allow_deny_and_interact_control(self):
        p,r=PolicyEngine().evaluate('browser.navigate','alice','browser:navigate',now());self.assertEqual(p.effect,PermissionEffect.ALLOW);p2,_=PolicyEngine().evaluate('browser.interact','alice','browser:interact',now());self.assertEqual(p2.effect,PermissionEffect.REQUIRE_APPROVAL);m,_,_=self.manager(policy=DenyPolicy())
        with self.assertRaises(PermissionError):m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')

    def test_owner_session_close_restart_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,a,s=self.manager(store);r=m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice',goal_id='g',task_run_id='t',trace_id='tr');self.assertEqual(r['status'],'VERIFIED');self.assertEqual(m.invocations(owner_user_id='bob',connector_id='browser'),[])
            with self.assertRaises(PermissionError):m.invoke_read('browser','read',{},'browser.read',owner_user_id='bob')
            row=m.invocations(owner_user_id='alice',connector_id='browser')[0];self.assertEqual(row['verification_status'],'VERIFIED');self.assertTrue(row['verification']['session_reference'].startswith('browser-session:'));self.assertNotIn('Visible text',json.dumps(row));self.assertEqual(a.close()['status'],'closed')
            a2=BrowserOrchestrator(EnvWrap(FakeGen1(FakeService())),owner_user_id='alice');m2=ConnectorManager(Gen2Store(Path(d)/'g2.sqlite3'),policy=PolicyEngine(),default_owner='alice');m2.register_descriptor(self.descriptor(),adapter=a2);m2.authorize('browser',['browser.navigate','browser.read','browser.interact'],owner_user_id='alice',actor='restart',reference='acceptance');m2.connect('browser',owner_user_id='alice');self.assertEqual(m2.health('browser',owner_user_id='alice')['status'],'HEALTHY');self.assertEqual(len(m2.invocations(owner_user_id='alice',connector_id='browser')),1);self.assertIsNone(a2._session)

    def test_connector_revoke_closes_active_gen1_session(self):
        m,a,s=self.manager();m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice');self.assertFalse(s.closed);rv=m.revoke('browser',owner_user_id='alice',actor='human');self.assertEqual(rv['connector_id'],'browser');self.assertTrue(s.closed);self.assertEqual(m.health('browser',owner_user_id='alice')['status'],'REVOKED')

    def test_screenshot_reference_bounded_but_runtime_unavailable(self):
        ref=BrowserScreenshotReference('artifact:shot','a'*64,1234);self.assertEqual(ref.size_bytes,1234)
        with self.assertRaises(ValueError):BrowserScreenshotReference('x','bad',1)
        m,a,_=self.manager();m.invoke_read('browser','navigate',{'url':'https://example.com'},'browser.navigate',owner_user_id='alice')
        with self.assertRaises(PermissionError):m.invoke('browser','interact',{'action':'screenshot'},'browser.interact',owner_user_id='alice',goal_id='g',task_run_id='t',approval=Approval())

    def test_personalagent_read_and_control_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(Path(d)/'g2.sqlite3');m,a,_=self.manager(store,owner='user');g=SimpleNamespace(health=lambda:{'tools':[],'tool_definitions':[]},retrieve_context=lambda *a,**k:{'source':'test','rendered':''},invoke=lambda *a,**k:ToolObservation(False,'x',{},{}))
            proposal=PlanProposal(uuid.uuid4().hex,'browse',[PlanProposalStep('n','Open page',['connector_read'],[],['verified'],{'connector_id':'browser','operation':'navigate','arguments':{'url':'https://example.com'},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'LOW',.95,[],now());agent=PersonalAgent(store,g,planner=StaticPlanner(proposal),connector_manager=m);res=agent.start('Open example.com.',user_id='user');self.assertEqual(res['status'],'COMPLETED');self.assertEqual(res['approvals'],[])
            target=a._last.links[0].url;proposal2=PlanProposal(uuid.uuid4().hex,'browse',[PlanProposalStep('i','Open observed link',['connector_invoke'],[],['verified'],{'connector_id':'browser','operation':'interact','arguments':{'action':'open_link','target_url':target},'classification':'PRIVATE'},30,0)],[{'description':'verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],now());agent2=PersonalAgent(store,g,planner=StaticPlanner(proposal2),connector_manager=m);first=agent2.start('Open the documentation link.',user_id='user');self.assertEqual(first['status'],'WAITING');agent2.decide_approval(first['approvals'][0],'approve',actor='human');done=agent2.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED')

    def test_existing_connectors_and_model_routes_unchanged(self):
        desc={x.connector_id:{c.operation for c in x.capabilities} for x in DESCRIPTORS};self.assertEqual(desc['gmail'],{'list_messages','get_message_metadata'});self.assertEqual(desc['calendar'],{'list_calendars','list_events','get_event'});self.assertEqual(desc['drive'],{'list_files','get_file_metadata'});self.assertEqual(desc['github'],{'get_user','list_repositories','get_repository','list_repository_contents','list_issues','list_pull_requests','list_workflows'})
        reg=build_gen2_model_registry(secrets=SecretResolver({'NVIDIA_API_KEY':'test-only'}));mm=ModelCapabilityManager(registry=reg,fallback_allowed=False);expected={'reasoning':'nvidia-nemotron-3.5-lightning','multimodal':'nvidia-nemotron-3-nano-omni','embedding':'nvidia-nemotron-3-embed-1b','reranking':'nvidia-llama-nemotron-rerank-vl-1b-v2','image_generation':'nvidia-flux-2-klein-4b','safety':'nvidia-nemotron-3.5-content-safety'};io={'reasoning':(['text'],['text']),'multimodal':(['image'],['text']),'embedding':(['text'],['embedding']),'reranking':(['text'],['ranking']),'image_generation':(['text'],['image']),'safety':(['text'],['safety'])}
        for cap,rid in expected.items():self.assertEqual(mm.route([cap],input_modalities=io[cap][0],output_modalities=io[cap][1]).selected.record_id,rid)

if __name__=='__main__':unittest.main()
