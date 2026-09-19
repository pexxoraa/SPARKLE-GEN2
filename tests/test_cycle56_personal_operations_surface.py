import json,tempfile,threading,unittest,urllib.request,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path

from sparkle.system import SparkleSystem
from sparkle_gen2.background import BackgroundTaskService
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.core_time import now
from sparkle_gen2.daily_os import DailyOperatingSystemService
from sparkle_gen2.dashboard import PersonalOperationsService,PersonalOperationsSnapshot
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.models import Goal,GoalStatus,PlanProposal,PlanProposalStep,TaskRun
from sparkle_gen2.notifications import NotificationCenter
from sparkle_gen2.personal_core import PersonalCore,build_server
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.world_model import WorldModel

class Context:
    def __init__(self,items=None):self.items=items or []
    def gather(self,goal):return {'goal':goal,'items':self.items,'item_count':len(self.items),'char_count':sum(len(str(x.get('value',''))) for x in self.items)}
class Models:
    def status(self,cap):
        if cap in {'reasoning','planning','coding','tool_use'}:return {'capability':cap,'status':'CONNECTED','route':{'selected':{'provider':'nvidia','model_id':'nvidia/reason','health':'HEALTHY'},'fallback':False,'selection_reason':'configured capability route'}}
        return {'capability':cap,'status':'EXTERNALLY_BLOCKED','route':{'selected':None,'fallback':False,'selection_reason':'no configured available model satisfies required capabilities/modalities'}}
class Diagnostics:
    def inspect(self):return {'healthy':False,'storage':{'available':True,'path':'/private/db.sqlite3'},'issues':[{'component':'connector','id':'gmail','cause':'EXTERNALLY_BLOCKED','token':'must-not-leak'}]}
class Connectors:
    def discover(self):return [{'name':'gmail'},{'name':'calendar'}]
    def health(self,name):return {'name':name,'status':'EXTERNALLY_BLOCKED','dependency':name+' OAuth','credential':'must-not-leak'}
class Devices:
    def discover(self):return [{'device_id':'robot1','kind':'robot','status':'OFFLINE','capabilities':['pose'],'last_seen':'2026-09-19T00:00:00+00:00'}]
    def health(self,did):return {'status':'EXTERNALLY_BLOCKED','dependency':'physical robot'}

def ctx_item(source,key,value,score=.9):return {'source':source,'key':key,'value':value,'score':score,'provenance':{'source':source}}
def daily_plan(brief_id,item_id,state='DONE'):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('update','Update exact Daily Brief item',['daily_brief_update'],[],['persisted state reread'],{'brief_id':brief_id,'item_id':item_id,'state':state},30,0)],[{'description':'daily item verified','verification_method':'all_steps_verified'}],'MEDIUM',.99,[],'test-only')
def ops_plan(day='2026-09-19'):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('ops','Read current personal operations',['operations_snapshot'],[],['bounded authoritative projection'],{'day':day},30,0)],[{'description':'operations snapshot verified','verification_method':'all_steps_verified'}],'LOW',.99,[],'test-only')
def request(url,*,token=None,data=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=(json.dumps(data).encode() if data is not None else None),headers=headers,method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())

class Cycle56Tests(unittest.TestCase):
    def make_service(self,d,owner='user'):
        store=Gen2Store(Path(d)/'g2.db');world=WorldModel(store);world.observe('robot1','robot',{'pose':{'x':1}}, {'source':'perception','observation_id':'obs-old'},observed_at=(datetime.now(UTC)-timedelta(seconds=40)).isoformat());daily=DailyOperatingSystemService(store,Context([ctx_item('tasks','priority','deadline today finish report')]));daily.generate(user_id=owner,day='2026-09-19');svc=PersonalOperationsService(store,daily_os=daily,diagnostics=Diagnostics(),model_manager=Models(),connectors=Connectors(),devices=Devices(),world=world,max_items=10);return store,world,daily,svc
    def seed_goal(self,store,gid,owner,status='WAITING',request='Prepare weekly plan',run_status='WAITING'):
        stamp=now();g=Goal(gid,request,request,status=GoalStatus(status),created_at=stamp,updated_at=stamp,user_id=owner,deadline=(datetime.now(UTC)+timedelta(hours=4)).isoformat());store.save_goal(g);r=TaskRun('run-'+gid,gid,'step1',[],[],['step1'],[],[],[],stamp,stamp,g.deadline,run_status,'trace-'+gid);store.save_task_run(r);return g,r
    def test_snapshot_schema_bounded_owner_daily_task_notification_failure_and_next_action(self):
        with tempfile.TemporaryDirectory() as d:
            store,world,daily,svc=self.make_service(d,'alice');self.seed_goal(store,'ga','alice',status='BLOCKED',request='Alice blocked task',run_status='BLOCKED');self.seed_goal(store,'gb','bob',request='Bob private task');BackgroundTaskService(store,lambda:None).create('ga');NotificationCenter(store).create('ops','Important update','Alice needs attention','HIGH');snap=svc.snapshot(owner_user_id='alice',day='2026-09-19');self.assertEqual(PersonalOperationsSnapshot(**snap).owner_user_id,'alice');self.assertTrue(snap['today']['daily_brief']['brief']);self.assertEqual({x['goal_id'] for x in snap['today']['active_work']},{'ga'});self.assertEqual({x['goal_id'] for x in snap['today']['active_goals']},{'ga'});self.assertTrue(snap['operations']['background_tasks']);self.assertTrue(snap['today']['notifications']);self.assertTrue(snap['today']['attention']);self.assertLessEqual(len(snap['today']['active_work']),10);self.assertNotIn('Bob private task',json.dumps(snap))
    def test_capabilities_external_block_connectors_diagnostics_stale_world_and_empty_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,svc=self.make_service(d);snap=svc.snapshot(day='2026-09-19');models={x['capability']:x for x in snap['intelligence']['capabilities']['models']};self.assertEqual(models['reasoning']['status'],'CONNECTED');self.assertEqual(models['multimodal']['status'],'EXTERNALLY_BLOCKED');self.assertEqual(snap['intelligence']['connectors']['items'][0]['status'],'EXTERNALLY_BLOCKED');self.assertEqual(snap['intelligence']['world_state']['items'][0]['freshness'],'STALE');self.assertFalse(snap['intelligence']['diagnostics']['healthy'])
        with tempfile.TemporaryDirectory() as d:
            empty=PersonalOperationsService(Gen2Store(Path(d)/'e.db')).snapshot(day='2026-09-19');self.assertEqual(empty['today']['daily_brief']['status'],'EMPTY');self.assertEqual(empty['intelligence']['connectors']['status'],'UNAVAILABLE');self.assertEqual(empty['intelligence']['world_state']['status'],'UNAVAILABLE')
    def test_no_secret_or_hidden_reasoning_leakage(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,_,svc=self.make_service(d);self.seed_goal(store,'g','user',request='Use token=supersecret123 safely');NotificationCenter(store).create('x','Credential','api_key=SECRET-VALUE','HIGH');snap=svc.snapshot(day='2026-09-19');text=json.dumps(snap);self.assertNotIn('supersecret123',text);self.assertNotIn('SECRET-VALUE',text);self.assertNotIn('must-not-leak',text);self.assertNotIn('/private/db.sqlite3',text);self.assertNotIn('chain_of_thought',text);self.assertNotIn('requested_scope',text)
    def test_restart_reconstructs_same_authoritative_state_and_freshness_remains_stale(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'g2.db';store,world,daily,svc=self.make_service(d);self.seed_goal(store,'g','user');a=svc.snapshot(day='2026-09-19');store2=Gen2Store(db);world2=WorldModel(store2);svc2=PersonalOperationsService(store2,daily_os=DailyOperatingSystemService(store2,Context()),model_manager=Models(),world=world2);b=svc2.snapshot(day='2026-09-19');self.assertEqual(a['today']['daily_brief']['brief']['brief_id'],b['today']['daily_brief']['brief']['brief_id']);self.assertEqual(a['today']['active_work'][0]['goal_id'],b['today']['active_work'][0]['goal_id']);self.assertEqual(b['intelligence']['world_state']['items'][0]['freshness'],'STALE')
    def test_personal_agent_reads_operations_without_approval(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,_,svc=self.make_service(d);self.seed_goal(store,'g','user');agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(ops_plan()),operations_service=svc);r=agent.start('What is happening right now?',user_id='user');self.assertEqual(r['status'],'COMPLETED');self.assertEqual(r['approvals'],[]);self.assertIn('Personal operations:',r['text']);self.assertTrue(any(x['component']=='operations_snapshot' and x['kind']=='action' for x in store.operation_traces(trace_id=r['trace_id'])))
    def test_http_operations_scope_redaction_and_pwa_surface(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,daily,svc=self.make_service(d);self.seed_goal(store,'g','user');agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(ops_plan()),daily_os_service=daily,operations_service=svc);core=PersonalCore((store,agent,SessionService(store)));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];_,en=request(base+'/api/enroll',data={'code':code,'name':'Ops','kind':'laptop','os':'Linux','capabilities':['task_status']});_,snap=request(base+'/api/operations?day=2026-09-19',token=en['token']);self.assertEqual(snap['operations']['pending_approvals'],[]);self.assertEqual(snap['today']['notifications'],[]);self.assertEqual(snap['intelligence']['world_state']['status'],'UNAVAILABLE')
                with urllib.request.urlopen(base+'/',timeout=5) as r:html=r.read().decode();self.assertIn('Personal operations',html);self.assertIn('Daily Brief',html);self.assertIn('Intelligence & state',html)
            finally:server.shutdown();server.server_close()
    def test_dashboard_approval_executes_existing_agent_path_and_rereads_state(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,daily,svc=self.make_service(d);brief=daily.inspect(user_id='user',day='2026-09-19');iid=brief.items[0]['item_id'];agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(daily_plan(brief.brief_id,iid)),daily_os_service=daily,operations_service=svc);pending=agent.start('Mark today priority done.',user_id='user');self.assertEqual(pending['status'],'WAITING');core=PersonalCore((store,agent,SessionService(store)));server=build_server(core,'127.0.0.1',0);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_address[1]}'
            try:
                code=core.devices.create_enrollment_code()['code'];_,en=request(base+'/api/enroll',data={'code':code,'name':'Ops','kind':'laptop','os':'Linux','capabilities':['task_status','approvals','notifications','device_management']});_,before=request(base+'/api/operations?day=2026-09-19',token=en['token']);self.assertEqual(len(before['operations']['pending_approvals']),1);aid=pending['approvals'][0];_,changed=request(base+f'/api/operations/approvals/{aid}/approve',token=en['token'],data={});self.assertEqual(changed['goal']['status'],'COMPLETED');self.assertEqual(changed['approval']['status'],'APPROVED');self.assertEqual(daily.inspect(user_id='user',brief_id=brief.brief_id).items[0]['state'],'DONE');_,after=request(base+'/api/operations?day=2026-09-19',token=en['token']);self.assertEqual(after['operations']['pending_approvals'],[]);self.assertEqual(after['today']['daily_brief']['completed_count'],1);self.assertTrue(any(x['goal_id']==pending['goal_id'] for x in after['operations']['recent_completed']))
            finally:server.shutdown();server.server_close()
    def test_dashboard_approved_scope_mutation_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,daily,svc=self.make_service(d);brief=daily.inspect(user_id='user',day='2026-09-19');iid=brief.items[0]['item_id'];agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(daily_plan(brief.brief_id,iid)),daily_os_service=daily,operations_service=svc);pending=agent.start('Mark priority done.',user_id='user');aid=pending['approvals'][0];plan=store.load_plan(store.load_goal(pending['goal_id']).plan_id);plan.steps[0].arguments['state']='DISMISSED';store.save_plan(plan);core=PersonalCore((store,agent,SessionService(store)));result=core.decide_operations_approval(aid,'approve',owner_user_id='user',actor='test-dashboard');self.assertEqual(result['goal']['status'],'BLOCKED');self.assertEqual(daily.inspect(user_id='user',brief_id=brief.brief_id).items[0]['state'],'OPEN')
    def test_dashboard_approval_owner_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,daily,svc=self.make_service(d,'alice');brief=daily.inspect(user_id='alice',day='2026-09-19');iid=brief.items[0]['item_id'];agent=PersonalAgent(store,LocalGen1Gateway(SparkleSystem()),planner=StaticPlanner(daily_plan(brief.brief_id,iid)),daily_os_service=daily,operations_service=svc);pending=agent.start('Update Alice brief.',user_id='alice');core=PersonalCore((store,agent,SessionService(store)))
            with self.assertRaisesRegex(PermissionError,'owner'):core.decide_operations_approval(pending['approvals'][0],'approve',owner_user_id='bob')

if __name__=='__main__':unittest.main()
