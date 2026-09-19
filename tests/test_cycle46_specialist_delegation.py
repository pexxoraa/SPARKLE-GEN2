import itertools,os,tempfile,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sparkle.contracts import ModelResponse,ToolCall
from sparkle.model import ModelAdapter
from sparkle.providers.mock import DeterministicAdapter
from sparkle.registry import ModelRegistry
from sparkle.system import SparkleSystem
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.delegation import DelegationRecord,DelegationRequest,SpecialistDelegationService
from sparkle_gen2.gen1 import LocalGen1Gateway,ToolObservation
from sparkle_gen2.models import PlanProposal,PlanProposalStep
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store


class CaptureAdapter(ModelAdapter):
    provider='test-harness';model_id='test-harness'
    def __init__(self,batches=None):self.requests=[];self.batches=None if batches is None else iter(batches)
    def complete(self,request):
        self.requests.append(request)
        if self.batches is None:return ModelResponse('bounded specialist output',self.model_id,self.provider,'stop')
        calls=next(self.batches);return ModelResponse('done' if not calls else '',self.model_id,self.provider,'stop' if not calls else 'tool_use',tool_calls=calls)
    def health(self):return {'configured':True}

def build_test_system(root,adapter):
    registry=ModelRegistry();registry.inject(registry.active_id,adapter);return SparkleSystem(model_registry=registry)

SAFE_CATALOG=[
 {'name':'research','capability':'reasoning','tools':['calculator','knowledge_search','knowledge_verify','memory_search','research_workspace']},
 {'name':'data_analysis','capability':'reasoning','tools':['calculator','data_analyze','file_read','knowledge_search','memory_search']},
 {'name':'system','capability':'reasoning','tools':['calculator','engineering_inspect','file_read','knowledge_search','memory_search']},
 {'name':'coding','capability':'coding','tools':['calculator','engineering_inspect','file_read','knowledge_search','memory_search','workspace_verify']},
 {'name':'learning','capability':'reasoning','tools':['calculator','knowledge_search','learning_progress','memory_search','memory_write','skill_search']},
]

class FakeGateway:
    def __init__(self,*,status='COMPLETED',block=None):self.status=status;self.block=block;self.delegate_calls=[];self.invoke_calls=[]
    def health(self):return {'available':True,'tools':['calculator'],'tool_definitions':[{'name':'calculator','parameters':{'type':'object'}}]}
    def retrieve_context(self,*a):return {'source':'fake','rendered':'bounded'}
    def invoke(self,tool,args):
        self.invoke_calls.append((tool,args));return ToolObservation(True,tool,{'value':703},{'verified':True,'method':'fake deterministic calculator'})
    def specialist_catalog(self):return list(SAFE_CATALOG)
    def specialist_limits(self):return {'max_specialists':4,'max_tool_calls':16,'max_rounds':4,'max_runtime_seconds':300,'cancellation':'pre_start_only','restart_resume':False}
    def delegate_specialists(self,objective,specialists,*,user_id,input_source):
        self.delegate_calls.append({'objective':objective,'specialists':list(specialists),'user_id':user_id,'input_source':input_source})
        if self.block is not None:self.block.wait(2)
        if self.status!='COMPLETED':
            return {'status':'FAILED','specialist_results':[],'findings':'','artifacts':[],'evidence':[],'confidence':0.0,'unresolved_items':['specialist failed'],'provenance':{'input_source':input_source,'user_id':user_id},'verification':{'verified':False,'method':'fake failure'},'failure':{'category':'EXECUTION','reason':'specialist failed'}}
        rows=[{'specialist':name,'status':'success','text':f'{name} result','tools':['knowledge_search'],'trace_id':f'g1-{name}'} for name in specialists]
        return {'status':'COMPLETED','specialist_results':rows,'findings':'Synthesized specialist evidence.','artifacts':[],'evidence':[{'specialist':x,'verified':True} for x in specialists],'confidence':.9,'unresolved_items':[],'provenance':{'gen1_final_trace_id':'g1-final','specialist_trace_ids':[f'g1-{x}' for x in specialists],'input_source':input_source,'user_id':user_id},'verification':{'verified':True,'method':'fake persistent Gen-1 traces','specialist_count':len(specialists)},'failure':None}

def delegation_plan(names):
 return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('delegate','Coordinate specialist analysis',['specialist_delegate'],[],['specialist evidence verified'],{'specialists':list(names),'objective':'Analyze the bounded project question','required_evidence':['persistent specialist trace']},30,0)],[{'description':'specialist delegation verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')

def calculator_plan():
 return PlanProposal(uuid.uuid4().hex,'x',[PlanProposalStep('calc','Calculate directly',['calculator'],[],['verified arithmetic'],{'expression':'700+3'},30,0)],[{'description':'direct action verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')


def sequential_delegation_plan():
 return PlanProposal(uuid.uuid4().hex,'x',[
  PlanProposalStep('research','Gather bounded research',['specialist_delegate'],[],['research verified'],{'specialists':['research'],'objective':'Gather verified project evidence'},30,0),
  PlanProposalStep('analyze','Analyze verified research',['specialist_delegate'],['research'],['analysis verified'],{'specialists':['data_analysis'],'objective':'Analyze the verified research evidence'},30,0),
 ],[{'description':'sequential specialist work verified','verification_method':'all_steps_verified'}],'LOW',.9,[],'test')

class Cycle46SpecialistDelegationTests(unittest.TestCase):
    def _service(self,d,gateway=None):
        gateway=gateway or FakeGateway();store=Gen2Store(Path(d)/'g.db');return store,gateway,SpecialistDelegationService(store,gateway,PolicyEngine())
    def _request(self,service,names=('research',),user_id='user-17'):
        return DelegationRequest('dlg-test','goal-1','task-1','trace-parent',user_id,'reasoning',list(names),'Analyze verified evidence',{},['read-only'],'2099-01-01T00:00:00+00:00','LOW',['trace evidence'],'now')

    def test_current_gen1_certified_limits_and_registry_are_consumable_without_execution(self):
        g=LocalGen1Gateway();limits=g.specialist_limits();names={x['name'] for x in g.specialist_catalog()}
        self.assertEqual(limits['max_specialists'],4);self.assertEqual(limits['max_tool_calls'],16);self.assertEqual(limits['max_rounds'],4);self.assertEqual(limits['max_runtime_seconds'],300);self.assertFalse(limits['restart_resume']);self.assertIn('research',names);self.assertIn('coding',names)
        budget=g.system.orchestrator._new_budget()
        with self.assertRaises(RuntimeError) as tools:budget.reserve(limits['max_tool_calls']+1)
        self.assertEqual(getattr(tools.exception,'orchestration_code',None),'tool_call_limit')
        budget.deadline=time.monotonic()-1
        with self.assertRaises(RuntimeError) as runtime:budget.check()
        self.assertEqual(getattr(runtime.exception,'orchestration_code',None),'workflow_deadline')

    def test_actual_gen1_run_multi_single_and_multi_are_verified_from_persistent_traces(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':d}):
            adapter=CaptureAdapter();gateway=LocalGen1Gateway(build_test_system(d,adapter))
            single=gateway.delegate_specialists('Bounded research',['research'],user_id='user-a',input_source='gen2-delegation:single-contract')
            self.assertEqual(single['status'],'COMPLETED');self.assertTrue(single['verification']['verified']);self.assertEqual([x['specialist'] for x in single['specialist_results']],['research'])
            multi=gateway.delegate_specialists('Research and analyze',['research','data_analysis'],user_id='user-b',input_source='gen2-delegation:multi-contract')
            self.assertEqual(multi['status'],'COMPLETED');self.assertTrue(multi['verification']['verified']);self.assertEqual([x['specialist'] for x in multi['specialist_results']],['research','data_analysis']);self.assertEqual(len(multi['provenance']['specialist_trace_ids']),2)
            self.assertTrue(all(r.metadata.get('user_id') in {'user-a','user-b'} for r in adapter.requests));self.assertEqual([r.metadata.get('user_id') for r in adapter.requests[:1]],['user-a']);self.assertTrue(all(r.metadata.get('user_id')=='user-b' for r in adapter.requests[1:]))

    def test_actual_gen1_tool_round_runtime_bounds_and_authorization_fail_closed(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':d}):
            too_many=[ToolCall(str(i),'calculator',{'expression':f'{i}+1'}) for i in range(17)];adapter=CaptureAdapter([too_many]);system=build_test_system(d,adapter);gateway=LocalGen1Gateway(system)
            with self.assertRaises(RuntimeError) as tool_limit:gateway.delegate_specialists('Calculate',['research'],user_id='u',input_source='gen2-delegation:tool-limit')
            self.assertEqual(getattr(tool_limit.exception,'orchestration_code',None),'tool_call_limit')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':d}):
            call=ToolCall('c','calculator',{'expression':'1+1'});adapter=CaptureAdapter([[call],[call]]);system=build_test_system(d,adapter);system.orchestrator.max_tool_rounds=0;gateway=LocalGen1Gateway(system)
            with self.assertRaises(RuntimeError) as rounds:gateway.delegate_specialists('Calculate',['research'],user_id='u',input_source='gen2-delegation:round-limit')
            self.assertEqual(getattr(rounds.exception,'orchestration_code',None),'tool_round_limit')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':d}):
            adapter=CaptureAdapter([[]]);system=build_test_system(d,adapter);system.orchestrator.max_workflow_seconds=1;gateway=LocalGen1Gateway(system);ticks=itertools.count()
            with patch('sparkle.orchestrator.time.monotonic',side_effect=lambda:next(ticks)*.6):
                with self.assertRaises(RuntimeError) as runtime:gateway.delegate_specialists('Analyze',['research'],user_id='u',input_source='gen2-delegation:runtime-limit')
            self.assertEqual(getattr(runtime.exception,'orchestration_code',None),'workflow_deadline')
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'SPARKLE_DATA_DIR':d}):
            unauthorized=ToolCall('bad','workspace_verify',{'project_name':'x','checks':[],'approved':True});adapter=CaptureAdapter([[unauthorized],[]]);gateway=LocalGen1Gateway(build_test_system(d,adapter));raw=gateway.delegate_specialists('Attempt unauthorized tool',['research'],user_id='u',input_source='gen2-delegation:authz')
            self.assertEqual(raw['status'],'FAILED');self.assertFalse(raw['verification']['verified']);self.assertIn('unauthorized_tool_request:workspace_verify',str(raw['failure']))

    def test_unknown_duplicate_and_count_bounds_fail_before_gen1(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,s=self._service(d)
            with self.assertRaisesRegex(ValueError,'unknown specialist'):s.prepare(self._request(s,('not_real',)))
            with self.assertRaisesRegex(ValueError,'duplicate'):s.prepare(self._request(s,('research','research')))
            with self.assertRaisesRegex(ValueError,'count exceeds'):s.prepare(self._request(s,('research','data_analysis','system','research2','research3')))
            self.assertEqual(g.delegate_calls,[])

    def test_approval_required_specialists_are_nondelegable(self):
        with tempfile.TemporaryDirectory() as d:
            _,g,s=self._service(d)
            with self.assertRaisesRegex(PermissionError,'coding:workspace_verify'):s.prepare(self._request(s,('coding',)))
            with self.assertRaisesRegex(PermissionError,'learning:memory_write'):s.prepare(self._request(s,('learning',)))
            self.assertEqual(g.delegate_calls,[])

    def test_identity_provenance_single_specialist_and_restart_safe_pending(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'g.db';g=FakeGateway();s=SpecialistDelegationService(Gen2Store(path),g,PolicyEngine());req=self._request(s,('research',),'authenticated-user');prepared=s.prepare(req);self.assertEqual(prepared.state,'PENDING')
            restarted=SpecialistDelegationService(Gen2Store(path),g,PolicyEngine());result=restarted.execute(req);self.assertEqual(result.status,'COMPLETED');self.assertTrue(result.verification['verified']);self.assertEqual(g.delegate_calls[0]['user_id'],'authenticated-user');self.assertEqual(result.provenance['parent_trace_id'],'trace-parent');self.assertEqual(result.provenance['user_id'],'authenticated-user');self.assertEqual(restarted.load(req.request_id).state,'COMPLETED')

    def test_inflight_restart_is_blocked_not_fake_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            store,g,s=self._service(d);req=self._request(s);store.save_delegation(DelegationRecord(req,'RUNNING',None,'now',False));result=SpecialistDelegationService(Gen2Store(store.path),g,PolicyEngine()).execute(req);self.assertEqual(result.status,'BLOCKED');self.assertFalse(result.verification['verified']);self.assertEqual(g.delegate_calls,[])

    def test_cancellation_request_discards_synchronous_result(self):
        with tempfile.TemporaryDirectory() as d:
            gate=threading.Event();store,g,s=self._service(d,FakeGateway(block=gate));req=self._request(s);out=[]
            thread=threading.Thread(target=lambda:out.append(s.execute(req)));thread.start()
            try:
                running=False
                for _ in range(200):
                    try:running=s.load(req.request_id).state=='RUNNING'
                    except KeyError:running=False
                    if running:break
                    time.sleep(.005)
                self.assertTrue(running);cancelled=s.cancel(req.request_id);self.assertEqual(cancelled.state,'CANCEL_REQUESTED');gate.set();thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(out[0].status,'CANCELLED');self.assertFalse(out[0].verification['verified']);self.assertEqual(s.load(req.request_id).state,'CANCELLED')
            finally:
                gate.set();thread.join(2)

    def test_personal_agent_single_specialist_completes_with_parent_trace(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeGateway();result=PersonalAgent(Gen2Store(Path(d)/'g.db'),g,planner=StaticPlanner(delegation_plan(['research']))).start('Prepare a bounded research brief.',user_id='u-42')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['checked'],['specialist_delegate']);self.assertEqual(len(result['delegations']),1);record=result['delegations'][0];self.assertEqual(record['state'],'COMPLETED');self.assertEqual(record['request']['user_id'],'u-42');self.assertEqual(record['request']['trace_id'],result['trace_id']);self.assertIn('I coordinated 1 bounded specialist',result['text']);self.assertEqual(g.invoke_calls,[])

    def test_personal_agent_multi_specialist_uses_one_bounded_gen1_call(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeGateway();result=PersonalAgent(Gen2Store(Path(d)/'g.db'),g,planner=StaticPlanner(delegation_plan(['research','data_analysis']))).start('Analyze the project evidence from two perspectives.',user_id='u-9')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(g.delegate_calls),1);self.assertEqual(g.delegate_calls[0]['specialists'],['research','data_analysis']);output=result['delegations'][0]['result'];self.assertEqual([x['specialist'] for x in output['specialist_results']],['research','data_analysis']);self.assertTrue(output['verification']['verified']);self.assertIn('Synthesized specialist evidence',result['text'])

    def test_sequential_specialist_step_receives_only_verified_dependency_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeGateway();result=PersonalAgent(Gen2Store(Path(d)/'g.db'),g,planner=StaticPlanner(sequential_delegation_plan())).start('Research then analyze the bounded project evidence.',user_id='u-chain')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(len(g.delegate_calls),2);self.assertEqual(g.delegate_calls[0]['specialists'],['research']);self.assertEqual(g.delegate_calls[1]['specialists'],['data_analysis']);self.assertIn('verified_dependency_results',g.delegate_calls[1]['objective']);self.assertIn('Synthesized specialist evidence.',g.delegate_calls[1]['objective']);self.assertEqual(len(result['delegations']),2)

    def test_simple_goal_does_not_delegate(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeGateway();result=PersonalAgent(Gen2Store(Path(d)/'g.db'),g,planner=StaticPlanner(calculator_plan())).start('Calculate 700 + 3.')
            self.assertEqual(result['status'],'COMPLETED');self.assertEqual(result['delegations'],[]);self.assertEqual(g.delegate_calls,[]);self.assertEqual(len(g.invoke_calls),1);self.assertIn('703',result['text'])

    def test_specialist_failure_cannot_false_complete(self):
        with tempfile.TemporaryDirectory() as d:
            g=FakeGateway(status='FAILED');result=PersonalAgent(Gen2Store(Path(d)/'g.db'),g,planner=StaticPlanner(delegation_plan(['research'])),max_replans=0).start('Research this safely.')
            self.assertNotEqual(result['status'],'COMPLETED');self.assertEqual(result['status'],'BLOCKED');record=result['delegations'][0];self.assertEqual(record['state'],'FAILED');self.assertFalse(record['result']['verification']['verified'])

    def test_arbitrary_or_privileged_specialist_cannot_be_executed_by_personal_agent(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('not_real','coding','learning'):
                with self.subTest(name=name):
                    g=FakeGateway();result=PersonalAgent(Gen2Store(Path(d)/(name+'.db')),g,planner=StaticPlanner(delegation_plan([name])),max_replans=0).start('Delegate safely.')
                    self.assertNotEqual(result['status'],'COMPLETED');self.assertEqual(g.delegate_calls,[])

if __name__=='__main__':unittest.main()
