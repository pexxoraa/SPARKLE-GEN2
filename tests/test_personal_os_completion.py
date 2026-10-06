import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.gen1 import LocalGen1Gateway
from sparkle_gen2.interfaces.http_server import PersonalCore,build_server
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.application.world.dashboard import PersonalOperationsService
from sparkle_gen2.application.system.diagnostics import SelfDiagnostics
from sparkle_gen2.learning_orchestration import LearningOrchestrator
from sparkle_gen2.experiments import ExperimentManager
from sparkle_gen2.application.personal_os import PersonalOSService


def plan():
    return PlanProposal('proposal','goal',[PlanProposalStep('calc','Calculate 2+2',['calculator'],[],['result is four'],{'expression':'2+2'},verification={'type':'returned_value','path':'value','expected':4})],
        [{'description':'all steps pass','verification_method':'all_steps_verified'}],'LOW',1,[],'test')


class PersonalOSCompletionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.store=Gen2Store(Path(self.directory.name)/'core.db')
        gateway=LocalGen1Gateway(SparkleSystem())
        operations=PersonalOperationsService(self.store,diagnostics=SelfDiagnostics(gateway,self.store))
        self.agent=PersonalAgent(self.store,gateway,planner=StaticPlanner(plan()),operations_service=operations)
        self.core=PersonalCore((self.store,self.agent,SessionService(self.store)))
        self.server=build_server(self.core,'127.0.0.1',0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_address[1]);self.token=self.enroll(['conversation','task_status','approvals'])

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(5);self.directory.cleanup()

    def request(self,path,*,data=None,token=None):
        headers={'Content-Type':'application/json','Authorization':'Bearer '+(token or self.token)}
        request=urllib.request.Request(self.base+path,headers=headers,data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(request,timeout=10) as response:return json.loads(response.read())
        except urllib.error.HTTPError as error:
            error.close();raise

    def enroll(self,capabilities):
        code=self.core.devices.create_enrollment_code()['code']
        request=urllib.request.Request(self.base+'/api/enroll',headers={'Content-Type':'application/json'},data=json.dumps({'code':code,'name':'Test browser','kind':'laptop','os':'Linux','capabilities':capabilities}).encode())
        with urllib.request.urlopen(request,timeout=5) as response:return json.loads(response.read())['token']

    def denied(self,path,*,data=None,token=None):
        with self.assertRaises(urllib.error.HTTPError) as error:self.request(path,data=data,token=token)
        try:self.assertEqual(error.exception.code,403 if data is not None else 401)
        finally:error.exception.close()

    def test_new_pages_read_persisted_records_and_enforce_scopes(self):
        result=self.agent.start('Calculate 2+2')
        for path in ('/api/state','/api/tasks','/api/approvals','/api/executions','/api/knowledge','/api/memory','/api/automations','/api/activity','/api/graph','/api/system'):
            with self.subTest(path=path):self.assertIsInstance(self.request(path),dict)
        detail=self.request('/api/executions/'+result['goal_id'])
        self.assertEqual(detail['run']['status'],'COMPLETED')
        self.assertIs(detail['plan']['steps'][0]['result']['verification']['verified'],True)
        limited=self.enroll(['conversation'])
        self.denied('/api/executions',token=limited)
        self.denied('/api/tasks/'+result['goal_id']+'/cancel',data={},token=limited)

    def test_other_owner_execution_is_hidden_and_control_denied(self):
        foreign=self.agent.start('Private goal belonging to someone else',user_id='other')
        self.assertEqual(self.request('/api/executions')['executions'],[])
        self.denied('/api/executions/'+foreign['goal_id'])
        self.denied('/api/tasks/'+foreign['goal_id']+'/cancel',data={})
        self.denied('/api/background',data={'goal_id':foreign['goal_id']})
        self.assertNotIn(foreign['goal_id'],json.dumps(self.request('/api/state')))
        self.assertEqual(self.request('/api/events')['events'],[])
        self.assertNotIn(foreign['goal_id'],json.dumps(self.request('/api/graph')))

    def test_goal_project_task_execution_result_are_connected_after_restart(self):
        goal=self.core.create_manual_goal('Build a robotics project')['goal']
        project=self.core.save_manual_record('project','Robotics',metadata={'goal_id':goal['goal_id']})
        task=self.core.create_manual_task('Verify robot math',metadata={'project_id':project['record_id']})
        linked=self.core.plan_os_item('task',task['goal_id'])
        self.assertEqual(linked['status'],'COMPLETED')
        graph=Gen2Store(self.store.path).graph_snapshot('user')
        edges={(e['from'],e['to'],e['type']) for e in graph['edges']}
        self.assertIn((project['record_id'],goal['goal_id'],'supports'),edges)
        self.assertIn((task['goal_id'],project['record_id'],'part_of'),edges)
        self.assertIn((linked['goal_id'],task['goal_id'],'part_of'),edges)
        self.assertTrue(any(e['type']=='produces' for e in graph['edges']))
        self.assertEqual(self.store.load_goal(task['goal_id']).metadata['execution_goal_id'],linked['goal_id'])

    def test_workflow_rejects_other_owner_and_record_type_substitution(self):
        other=self.core.save_manual_record('project','Private',owner_user_id='other')
        with self.assertRaises(PermissionError):self.core.plan_os_item('project',other['record_id'])
        project=self.core.save_manual_record('project','Own')
        with self.assertRaises(ValueError):self.core.plan_os_item('skill',project['record_id'])
        self.assertEqual(self.store.all_task_runs(),[])

    def test_graph_removes_deleted_records_and_execution_references(self):
        result=self.agent.start('Calculate 2+2')
        project=self.core.save_manual_record('project','Temporary')
        self.core.delete_manual_record(project['record_id'])
        self.core.delete_goal(result['goal_id'])
        graph=self.request('/api/graph')
        self.assertFalse(any(n['id']==project['record_id'] or n.get('goal_id')==result['goal_id'] for n in graph['nodes']))
        self.assertEqual(graph['edges'],[])

    def test_manual_task_owner_is_preserved_in_views(self):
        task=self.core.create_manual_task('Owned task',owner_user_id='other')
        self.assertEqual(self.core.task_view(),[])
        self.assertEqual(self.core.task_view(owner_user_id='other')[0]['goal_id'],task['goal_id'])

    def test_manual_os_update_and_delete_routes_persist_actual_changes(self):
        created=[('goals',self.request('/api/os/goals',data={'title':'Original'})['goal']['goal_id']),
                 ('tasks',self.request('/api/os/tasks',data={'title':'Original'})['goal_id']),
                 ('records',self.request('/api/os/records',data={'record_type':'project','title':'Original'})['record_id'])]
        for collection,identity in created:
            with self.subTest(collection=collection):
                changed=self.request('/api/os/'+collection+'/'+identity,data={'title':'Updated','priority':8})
                self.assertEqual(changed.get('title') or changed.get('normalized_objective'),'Updated')
                persisted=self.store.load_os_record(identity) if collection=='records' else self.store.load_goal(identity).to_dict()
                self.assertEqual(persisted.get('title') or persisted.get('normalized_objective'),'Updated')
                self.assertEqual(self.request('/api/os/'+collection+'/'+identity+'/delete',data={})['status'],'DELETED')
                with self.assertRaises(KeyError):self.store.load_os_record(identity) if collection=='records' else self.store.load_goal(identity)

    def test_memory_review_requires_owner_and_approval_scope(self):
        owned=self.agent.start('I prefer weekly summaries.')
        candidate=self.agent.memory.get(self.store.memory_candidates(goal_id=owned['goal_id'])[0]['candidate_id'])
        self.assertEqual(self.request('/api/memory')['candidates'][0]['state'],'PROPOSED')
        limited=self.enroll(['conversation']);self.denied('/api/memory/'+candidate.candidate_id+'/reject',data={},token=limited)
        rejected=self.request('/api/memory/'+candidate.candidate_id+'/reject',data={})
        self.assertEqual(rejected['state'],'REJECTED')
        other=self.agent.start('I prefer monthly summaries.',user_id='other')
        foreign=self.agent.memory.get(self.store.memory_candidates(goal_id=other['goal_id'])[0]['candidate_id'])
        self.denied('/api/memory/'+foreign.candidate_id+'/approve',data={})

    def test_learning_skill_evidence_is_persistent_and_connected(self):
        self.agent.learning=LearningOrchestrator(self.store,None)
        plan=self.core.create_manual_learning('Robotics','Understand controls',['Feedback'])['plan']
        skill=self.core.save_manual_record('skill','Control systems',metadata={'learning_plan_id':plan['plan_id']})
        self.agent.learning.assess(plan['plan_id'],owner_user_id='user',unit_id=plan['units'][0]['unit_id'],score=.9,evidence_reference='human-reviewed-exercise:1')
        graph=Gen2Store(self.store.path).graph_snapshot('user')
        self.assertTrue(any(e['from']==skill['record_id'] and e['to']==plan['plan_id'] for e in graph['edges']))
        self.assertTrue(any(e['type']=='assesses' for e in graph['edges']))

    def test_research_experiment_evidence_knowledge_links_and_owner_isolation(self):
        research=self.core.save_manual_record('research','Controller comparison')
        manager=ExperimentManager(self.store)
        experiment=manager.create('A improves stability','Compare bounded measurements',research_id=research['record_id'])
        manager.record_result(experiment.experiment_id,{'metrics':{'error':.2}},verification={'verified':True,'method':'trusted test runner'})
        manager.conclude(experiment.experiment_id,'Recorded comparison shows error .2.')
        graph=Gen2Store(self.store.path).graph_snapshot('user')
        self.assertTrue(any(e['from']==experiment.experiment_id and e['to']==research['record_id'] for e in graph['edges']))
        self.assertTrue(any(n['type']=='knowledge' for n in graph['nodes']))
        self.assertEqual(self.core.os_snapshot(owner_user_id='other')['research'],[])

    def test_agent_selection_preserves_request_and_reaches_plan(self):
        self.core.agent_select('research')
        conversation=self.core.conversations.send('Calculate 2+2')
        goal=self.store.load_goal(conversation['result']['goal_id'])
        self.assertEqual(goal.user_request,'Calculate 2+2')
        self.assertEqual(goal.metadata['agent_profile']['agent_id'],'research')
        self.assertEqual(self.store.load_plan(goal.plan_id).steps[0].preferred_agent,'research')

    def test_bounded_project_execution_preserves_direction_and_completion_state(self):
        goal=self.core.create_manual_goal('Build the entire robotics system')['goal']
        project=self.core.save_manual_record('project','Robotics',metadata={'goal_id':goal['goal_id']})
        result=self.core.plan_os_item('project',project['record_id'])
        self.assertEqual(result['status'],'COMPLETED')
        persisted=self.store.load_os_record(project['record_id'])
        self.assertEqual(persisted['status'],'ACTIVE')
        self.assertEqual(persisted['metadata']['goal_id'],goal['goal_id'])
        self.assertEqual(persisted['metadata']['execution_goal_id'],result['goal_id'])
        edges=Gen2Store(self.store.path).graph_snapshot('user')['edges']
        self.assertTrue(any(e['from']==project['record_id'] and e['to']==goal['goal_id'] and e['type']=='supports' for e in edges))
        self.assertTrue(any(e['from']==project['record_id'] and e['to']==result['goal_id'] and e['type']=='executed_by' for e in edges))

    def test_graph_changes_and_clears_links_without_stale_or_foreign_edges(self):
        first=self.core.create_manual_goal('First')['goal']['goal_id']
        second=self.core.create_manual_goal('Second')['goal']['goal_id']
        foreign=self.core.create_manual_goal('Private',owner_user_id='other')['goal']['goal_id']
        project=self.core.save_manual_record('project','Linked',metadata={'goal_id':first})
        for target in (second,'',foreign):
            self.core.update_manual_record(project['record_id'],{'goal_id':target})
            edges=Gen2Store(self.store.path).graph_snapshot('user')['edges']
            linked=[e['to'] for e in edges if e['from']==project['record_id'] and e['type']=='supports']
            self.assertEqual(linked,[second] if target==second else [])

    def test_application_facade_translates_payloads_and_enforces_owner_and_kind(self):
        service=PersonalOSService(self.core)
        goal=service.create_goal({'title':'Facade goal'},owner_user_id='other')['goal']
        project=service.save_record('project',{'title':'Facade project','metadata':{'goal_id':goal['goal_id']}},owner_user_id='other')
        task=service.create_task({'title':'Facade task','priority':8,'metadata':{'project_id':project['record_id']}},owner_user_id='other')
        self.assertEqual(self.store.load_goal(task['goal_id']).priority,8)
        self.assertEqual(service.snapshot()['projects'],[])
        self.assertEqual(service.snapshot(owner_user_id='other')['projects'][0]['record_id'],project['record_id'])
        with self.assertRaises(PermissionError):service.update_record('project',project['record_id'],{'title':'Denied'})
        with self.assertRaises(ValueError):service.delete_record('skill',project['record_id'],owner_user_id='other')
        changed=service.update_record('project',project['record_id'],{'title':'Changed'},owner_user_id='other')
        self.assertEqual(changed['title'],'Changed')
        service.delete_record('project',project['record_id'],owner_user_id='other')
        with self.assertRaises(KeyError):self.store.load_os_record(project['record_id'])
