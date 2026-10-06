import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sparkle_gen2.application.execution.verification import StepVerifier
from sparkle_gen2.application.execution.budgets import ResourceBudget
from sparkle_gen2.application.system.tool_system import CapabilityCatalog
from sparkle_gen2.domain.contracts.tool_protocol import input_errors
from sparkle_gen2.gen1 import ToolObservation
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.planner import StaticPlanner
from sparkle_gen2.storage import Gen2Store
from test_execution_completion import Gateway,proposal


class ToolProtocolCompletionTests(unittest.TestCase):
    def test_resource_budget_counts_survive_restart_and_unknown_tokens_block(self):
        runs=[{'iterations':3,'active_runtime_seconds':5,'resource_usage':{'planning_calls':2,'reported_tokens':30}},
              {'iterations':1,'active_runtime_seconds':2,'resource_usage':{'planning_calls':1}}]
        usage=ResourceBudget.usage(runs)
        self.assertEqual(usage['tool_calls'],4);self.assertEqual(usage['planning_calls'],3)
        self.assertEqual(usage['runtime_seconds'],7);self.assertIsNone(usage['reported_tokens'])
        self.assertFalse(ResourceBudget({'reported_tokens':100}).check(usage)['allowed'])
        self.assertFalse(ResourceBudget({'planning_calls':3}).check(usage,reservations={'planning_calls':1})['allowed'])

    def test_catalog_uses_real_availability_policy_and_handler(self):
        health={'tools':['calculator','memory_write','unregistered'],'native_tools':['calculator'],
                'tool_definitions':[{'name':'calculator','parameters':{'type':'object','required':['expression']}}]}
        catalog=CapabilityCatalog.from_health(health,PolicyEngine(),timestamp='test',agent_ids=('personal','research'))
        self.assertEqual([x.identity for x in catalog.list()],['calculator','memory_write'])
        write=catalog.get('memory_write').metadata['tool_definition']
        self.assertEqual(write['permission']['effect'],'REQUIRE_APPROVAL')
        self.assertTrue(write['risk']['state_changing'])
        self.assertEqual(catalog.get('calculator').metadata['execution_handler'],'gen1_gateway')
        self.assertEqual(catalog.get('calculator').input_schema['required'],['expression'])

    def test_schema_rejects_nested_types_ranges_and_nonfinite_without_values(self):
        schema={'type':'object','properties':{'score':{'type':'number','minimum':0,'maximum':1},'nested':{'type':'object','properties':{'secret':{'type':'integer'}},'additionalProperties':False}},'required':['score'],'additionalProperties':False}
        for value in ({'score':True},{'score':float('nan')},{'score':2},{'score':.5,'nested':{'secret':'private-value'}},{'score':.5,'extra':'private-value'}):
            errors=input_errors(value,schema)
            self.assertTrue(errors);self.assertNotIn('private-value',str(errors))
        self.assertEqual(input_errors({'score':.5,'nested':{'secret':1}},schema),[])

    def test_explicit_return_value_mismatch_blocks_successful_tool(self):
        with tempfile.TemporaryDirectory() as d:
            plan=proposal();plan.steps[0].verification={'type':'returned_value','path':'calls','expected':999}
            agent=PersonalAgent(Gen2Store(Path(d)/'core.db'),Gateway(),planner=StaticPlanner(plan))
            result=agent.start('Calculate')
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['verified'],[])
            step=agent.store.load_plan(agent.store.load_goal(result['goal_id']).plan_id).steps[0]
            self.assertFalse(step.result['tool_output']['verification']['verified'])

    def test_verifiers_require_native_observation_and_check_criteria(self):
        verifier=StepVerifier()
        cases=[('http_status',{'status':200},'status'),('file_exists',{'exists':True},'exists'),
               ('command_result',{'returncode':0},'returncode'),('test_result',{'status':'passed'},'status'),
               ('artifact_exists',{'id':'artifact:1'},'id')]
        for kind,data,path in cases:
            step=SimpleNamespace(verification_strategy={'type':kind,'path':path})
            with self.subTest(kind=kind):
                self.assertTrue(verifier.verify(step,ToolObservation(True,'adapter',data,{'verified':True}))['verified'])
                self.assertFalse(verifier.verify(step,ToolObservation(True,'adapter',data,{'verified':False}))['verified'])

    def test_custom_verifier_is_explicit_and_unavailable_is_blocked(self):
        verifier=StepVerifier();step=SimpleNamespace(verification_strategy={'type':'custom','verifier':'check'})
        observation=ToolObservation(True,'adapter',{'result':4},{'verified':True})
        self.assertFalse(verifier.verify(step,observation)['verified'])
        verifier.register('check',lambda _s,o,_v:o.output['result']==4)
        self.assertTrue(verifier.verify(step,observation)['verified'])

    def test_unknown_verification_is_rejected_before_tool_execution(self):
        with tempfile.TemporaryDirectory() as d:
            plan=proposal();plan.steps[0].verification={'type':'pretend_success'};gateway=Gateway()
            agent=PersonalAgent(Gen2Store(Path(d)/'core.db'),gateway,planner=StaticPlanner(plan))
            result=agent.start('Calculate')
            self.assertEqual(result['status'],'BLOCKED');self.assertEqual(gateway.calls,[])
            self.assertEqual(agent.store.load_task_run_for_goal(result['goal_id']).status,'BLOCKED')
