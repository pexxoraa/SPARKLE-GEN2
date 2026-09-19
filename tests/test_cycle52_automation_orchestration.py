import os,tempfile,unittest,uuid
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.automation_orchestration import AutomationOrchestrator
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store

class FakeAgent:
    def __init__(self,state='COMPLETED',gen1=None):self.state=state;self.calls=[];self.gen1=gen1
    def start(self,prompt,*,user_id='user'):
        gid='auto-goal-'+uuid.uuid4().hex;self.calls.append(('start',prompt,user_id,gid));return {'goal_id':gid,'status':self.state,'trace_id':'trace-'+gid,'text':'automated result'}
    def resume(self,goal_id):self.calls.append(('resume',goal_id));return {'goal_id':goal_id,'status':self.state,'trace_id':'trace-'+goal_id,'text':'automated result','approvals':[]}

def auto_plan(arguments,tool='automation_create'):
    return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('auto','Manage the approved automation',[tool],[],['automation state reread'],arguments,30,0)],[{'description':'automation state verified','verification_method':'all_steps_verified'}],'MEDIUM',.95,[],'test-only')

def env_case(test,d):
    e=patch.dict(os.environ,{'SPARKLE_DATA_DIR':str(Path(d)/'gen1')});e.start();test.addCleanup(e.stop);Path(os.environ['SPARKLE_DATA_DIR']).mkdir(exist_ok=True)

def gateway():return LocalGen1Gateway(SparkleSystem())

class Cycle52AutomationTests(unittest.TestCase):
    def service(self,d,agent=None):
        env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');fake=agent or FakeAgent();svc=AutomationOrchestrator(store,g,lambda:fake);return store,g,fake,svc

    def test_personal_agent_create_requires_exact_human_approval(self):
        with tempfile.TemporaryDirectory() as d:
            env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');args={'name':'Weekly plan','trigger_type':'scheduled','prompt':'Prepare my weekly plan','schedule_kind':'weekly','schedule':'Sunday 09:00','next_run_at':(datetime.now(UTC)+timedelta(days=1)).isoformat(),'required_capabilities':['planning','reasoning']};agent=PersonalAgent(store,g,planner=StaticPlanner(auto_plan(args)));first=agent.start('Every Sunday prepare my weekly plan.',user_id='alice');self.assertEqual(first['status'],'WAITING');self.assertEqual(len(first['approvals']),1);self.assertEqual(g.system.automations.list(),[]);approval=store.load_approval(first['approvals'][0]);self.assertEqual(approval.capability,'automation_create');self.assertIn('"prompt":"Prepare my weekly plan"',approval.requested_scope);self.assertEqual(approval.risk.value,'MEDIUM');agent.decide_approval(approval.approval_id,'approve',actor='human-reviewer');done=agent.resume(first['goal_id']);self.assertEqual(done['status'],'COMPLETED');items=g.system.automations.list();self.assertEqual(len(items),1);view=agent.automation.inspect(items[0]['id']);self.assertEqual(view['object']['owner_user_id'],'alice');self.assertEqual(view['object']['trigger_type'],'scheduled');self.assertEqual(view['object']['required_capabilities'],['planning','reasoning'])

    def test_approval_scope_mutation_blocks_without_creating_second_automation(self):
        with tempfile.TemporaryDirectory() as d:
            env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');args={'name':'Weekly plan','trigger_type':'scheduled','prompt':'Prepare plan A','schedule_kind':'weekly','next_run_at':(datetime.now(UTC)+timedelta(days=1)).isoformat()};agent=PersonalAgent(store,g,planner=StaticPlanner(auto_plan(args)));first=agent.start('Schedule plan A',user_id='alice');aid=first['approvals'][0];plan=store.load_plan(store.load_goal(first['goal_id']).plan_id);plan.steps[0].arguments['prompt']='Prepare plan B';store.save_plan(plan);agent.decide_approval(aid,'approve',actor='human-reviewer');result=agent.resume(first['goal_id']);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.system.automations.list(),[]);self.assertTrue(any(e['event_type']=='automation_approval_scope_mismatch' for e in store.events(first['goal_id'])))

    def test_model_supplied_approval_field_is_rejected_by_schema(self):
        with tempfile.TemporaryDirectory() as d:
            env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');args={'name':'x','trigger_type':'scheduled','prompt':'x','schedule_kind':'once','next_run_at':(datetime.now(UTC)+timedelta(hours=1)).isoformat(),'approved':True};result=PersonalAgent(store,g,planner=StaticPlanner(auto_plan(args))).start('schedule x');self.assertEqual(result['status'],'BLOCKED');self.assertEqual(g.system.automations.list(),[])

    def test_scheduled_trigger_executes_through_background_and_notifies(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,fake,svc=self.service(d);past=(datetime.now(UTC)-timedelta(seconds=2)).isoformat();view=svc.create(owner_user_id='u',source_goal_id='source',name='once',trigger_type='scheduled',prompt='do work',schedule_kind='once',next_run_at=past);runs=svc.run_due(datetime.now(UTC));self.assertEqual(len(runs),1);self.assertEqual(runs[0]['status'],'success');after=svc.inspect(view['automation']['id']);self.assertEqual(after['object']['status'],'COMPLETED');self.assertEqual(after['object']['verification_state'],'VERIFIED');self.assertTrue(after['object']['last_goal_id']);self.assertTrue(after['object']['last_background_id']);self.assertEqual(len(store.background_tasks()),1);self.assertTrue(any(n['title']=='Background task complete' for n in store.notifications()));self.assertEqual(len(fake.calls),3)

    def test_weekly_schedule_survives_restart_and_next_trigger_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,fake,svc=self.service(d);past=(datetime.now(UTC)-timedelta(days=1)).isoformat();created=svc.create(owner_user_id='u',source_goal_id='g',name='weekly',trigger_type='scheduled',prompt='weekly work',schedule_kind='weekly',schedule='Sunday 09:00',next_run_at=past);aid=created['automation']['id'];svc.run_due(datetime.now(UTC));next_run=svc.inspect(aid)['automation']['next_run_at'];self.assertIsNotNone(next_run);g2=LocalGen1Gateway(SparkleSystem());store2=Gen2Store(Path(d)/'g2.db');fake2=FakeAgent();svc2=AutomationOrchestrator(store2,g2,lambda:fake2);recovered=svc2.inspect(aid);self.assertEqual(recovered['automation']['next_run_at'],next_run);self.assertEqual(recovered['object']['owner_user_id'],'u');self.assertEqual(recovered['object']['status'],'ACTIVE')

    def test_event_condition_and_deadline_triggers_use_bounded_proactive_alerts(self):
        specs=[('event',{'alert':'research_change'}),('condition',{'alert':'project_incomplete','category':'projects'}),('deadline',{'alert':'deadline_approaching','category':'tasks'})]
        for trigger,condition in specs:
            with self.subTest(trigger=trigger),tempfile.TemporaryDirectory() as d:
                _,_,fake,svc=self.service(d);created=svc.create(owner_user_id='u',source_goal_id='g',name=trigger,trigger_type=trigger,prompt='react',condition=condition);aid=created['automation']['id'];alert={'type':condition['alert']}
                if condition.get('category'):alert['category']=condition['category']
                svc.runner.base.proactive.inspect=lambda current,a=alert:[dict(a)];current=datetime.now(UTC);first=svc.run_due(current);second=svc.run_due(current);self.assertEqual(len(first),1);self.assertEqual(second,[]);item=svc.inspect(aid)['automation'];self.assertTrue(item['enabled']);self.assertEqual(item['last_status'],'success');self.assertEqual(len([c for c in fake.calls if c[0]=='start']),1)

    def test_pause_resume_cancel_and_owner_binding(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,svc=self.service(d);future=(datetime.now(UTC)+timedelta(days=1)).isoformat();aid=svc.create(owner_user_id='alice',source_goal_id='g',name='ctl',trigger_type='scheduled',prompt='x',schedule_kind='daily',next_run_at=future)['automation']['id'];self.assertFalse(svc.pause(aid,'alice')['automation']['enabled']);self.assertTrue(svc.resume(aid,'alice')['automation']['enabled']);before=svc.inspect(aid)['automation']['enabled']
            with self.assertRaisesRegex(PermissionError,'owner mismatch'):svc.pause(aid,'mallory')
            self.assertEqual(svc.inspect(aid)['automation']['enabled'],before);cancelled=svc.cancel(aid,'alice');self.assertFalse(cancelled['automation']['enabled']);self.assertEqual(cancelled['object']['status'],'CANCELLED')

    def test_run_now_is_due_once_and_condition_run_now_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,fake,svc=self.service(d);future=(datetime.now(UTC)+timedelta(days=10)).isoformat();aid=svc.create(owner_user_id='u',source_goal_id='g',name='future',trigger_type='scheduled',prompt='x',schedule_kind='once',next_run_at=future)['automation']['id'];svc.run_now(aid,'u');now=datetime.now(UTC)+timedelta(seconds=2);self.assertEqual(len(svc.run_due(now)),1);self.assertEqual(svc.run_due(now),[]);self.assertEqual(len([x for x in fake.calls if x[0]=='start']),1)
        with tempfile.TemporaryDirectory() as d:
            _,_,_,svc=self.service(d);aid=svc.create(owner_user_id='u',source_goal_id='g',name='cond',trigger_type='event',prompt='x',condition={'alert':'research_change'})['automation']['id']
            with self.assertRaisesRegex(ValueError,'trigger evidence'):svc.run_now(aid,'u')

    def test_failure_is_truthful_and_background_state_and_notification_persist(self):
        with tempfile.TemporaryDirectory() as d:
            store,_,fake,svc=self.service(d,FakeAgent('BLOCKED'));past=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();aid=svc.create(owner_user_id='u',source_goal_id='g',name='fail',trigger_type='scheduled',prompt='fail',schedule_kind='once',next_run_at=past)['automation']['id'];runs=svc.run_due(datetime.now(UTC));self.assertEqual(runs[0]['status'],'failure');view=svc.inspect(aid);self.assertEqual(view['object']['status'],'FAILED');self.assertEqual(view['object']['verification_state'],'FAILED');self.assertEqual(store.background_tasks()[0].state,'BLOCKED');self.assertTrue(any(n['title']=='Background task needs attention' for n in store.notifications()))

    def test_optional_model_requirement_blocks_without_substitution(self):
        with tempfile.TemporaryDirectory() as d:
            env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');fake=FakeAgent(gen1=g);svc=AutomationOrchestrator(store,g,lambda:fake);past=(datetime.now(UTC)-timedelta(seconds=1)).isoformat();aid=svc.create(owner_user_id='u',source_goal_id='g',name='voice',trigger_type='scheduled',prompt='voice task',schedule_kind='once',next_run_at=past,required_capabilities=['voice','reasoning'])['automation']['id'];runs=svc.run_due(datetime.now(UTC));self.assertEqual(runs[0]['status'],'failure');self.assertEqual(fake.calls,[]);attempts=svc.inspect(aid)['attempts'];self.assertEqual(attempts[0]['error_type'],'RuntimeError')

    def test_unknown_model_capability_and_invalid_schedule_time_are_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,_,svc=self.service(d)
            with self.assertRaisesRegex(ValueError,'required capabilities'):svc.create(owner_user_id='u',source_goal_id='g',name='badcap',trigger_type='scheduled',prompt='x',schedule_kind='once',next_run_at=datetime.now(UTC).isoformat(),required_capabilities=['reasoning','not_a_capability'])
            with self.assertRaisesRegex(ValueError,'offset-aware ISO'):svc.create(owner_user_id='u',source_goal_id='g',name='badtime',trigger_type='scheduled',prompt='x',schedule_kind='once',next_run_at='tomorrow')
            self.assertEqual(g.system.automations.list(),[])

    def test_outer_retries_are_forbidden_because_personal_agent_owns_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,svc=self.service(d)
            with self.assertRaisesRegex(ValueError,'exactly one outer attempt'):svc.create(owner_user_id='u',source_goal_id='g',name='retry',trigger_type='scheduled',prompt='x',schedule_kind='once',next_run_at=datetime.now(UTC).isoformat(),max_attempts=2)

    def test_personal_agent_controls_all_require_human_approval_and_reread(self):
        with tempfile.TemporaryDirectory() as d:
            env_case(self,d);g=gateway();store=Gen2Store(Path(d)/'g2.db');future=(datetime.now(UTC)+timedelta(days=2)).isoformat();creator=PersonalAgent(store,g,planner=StaticPlanner(auto_plan({'name':'controlled','trigger_type':'scheduled','prompt':'work','schedule_kind':'daily','next_run_at':future})));first=creator.start('Create controlled automation',user_id='alice');creator.decide_approval(first['approvals'][0],'approve',actor='human-reviewer');created=creator.resume(first['goal_id']);aid=g.system.automations.list()[0]['id'];self.assertEqual(created['status'],'COMPLETED')
            expected={'automation_pause':False,'automation_resume':True,'automation_run_now':True,'automation_cancel':False}
            for tool,enabled in expected.items():
                with self.subTest(tool=tool):
                    agent=PersonalAgent(store,g,planner=StaticPlanner(auto_plan({'automation_id':aid},tool=tool)));pending=agent.start(tool.replace('_',' '),user_id='alice');self.assertEqual(pending['status'],'WAITING');self.assertEqual(len(pending['approvals']),1);agent.decide_approval(pending['approvals'][0],'approve',actor='human-reviewer');done=agent.resume(pending['goal_id']);self.assertEqual(done['status'],'COMPLETED');self.assertEqual(agent.automation.inspect(aid)['automation']['enabled'],enabled)

    def test_stale_running_claim_restart_recovers_to_eligible_not_inflight_resume(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,_,svc=self.service(d);past=(datetime.now(UTC)-timedelta(seconds=2)).isoformat();aid=svc.create(owner_user_id='u',source_goal_id='g',name='recover',trigger_type='scheduled',prompt='x',schedule_kind='daily',next_run_at=past)['automation']['id'];claimed=g.system.automations.claim_due(datetime.now(UTC).isoformat(),claim_token='a'*32,lease_seconds=30);self.assertEqual(len(claimed),1);future=(datetime.now(UTC)+timedelta(seconds=31)).isoformat();g2=LocalGen1Gateway(SparkleSystem());store2=Gen2Store(Path(d)/'g2.db');svc2=AutomationOrchestrator(store2,g2,lambda:FakeAgent());recovered=g2.system.automations.recover_stale_claims(future);self.assertEqual(recovered,1);item=svc2.inspect(aid)['automation'];self.assertTrue(item['enabled']);self.assertEqual(item['last_status'],'recovered');runs=[x for x in g2.system.automations.list_runs(limit=20) if x['automation_id']==aid];self.assertEqual(runs[0]['status'],'recovered');self.assertEqual(runs[0]['error_type'],'AutomationLeaseExpired')

    def test_policy_requires_approval_for_all_state_changing_controls(self):
        p=PolicyEngine()
        for cap in ('automation_create','automation_pause','automation_resume','automation_cancel','automation_run_now'):
            permission,risk=p.evaluate(cap,'user','scope',datetime.now(UTC).isoformat());self.assertEqual(permission.effect.value,'REQUIRE_APPROVAL');self.assertEqual(risk.level.value,'MEDIUM')

if __name__=='__main__':unittest.main()
