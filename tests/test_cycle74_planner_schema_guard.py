import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from sparkle_gen2.core import PersonalAgent
from sparkle_gen2.models import ModelProvenance,PlanProposal,PlanProposalStep
from sparkle_gen2.planner import Gen1PlannerModel
from sparkle_gen2.policy import PolicyEngine
from sparkle_gen2.storage import Gen2Store
from sparkle_gen2.validation import PlanValidationError,PlanValidator


class FakeRouter:
    def __init__(self,payload):
        self.payload=payload
        self.last_request=None

    def complete(self,request,*_args,**_kwargs):
        self.last_request=request
        decision=SimpleNamespace(
            provider='nvidia',
            model='nvidia/nemotron-test',
            capability='reasoning',
            fallback=False,
            selection_reason='test',
            health='HEALTHY',
            record_id='test-record',
        )
        response=SimpleNamespace(
            text=json.dumps(self.payload),
            provider_request_id='test-request',
        )
        return decision,response


class FakePlanningGateway:
    def __init__(self,payload):
        self.router=FakeRouter(payload)
        self.system=SimpleNamespace(model_router=self.router)
        self.capability_router=None


class FakeAgentGateway:
    def health(self):
        return {
            'tools':['operations_snapshot'],
            'tool_definitions':[{
                'name':'operations_snapshot',
                'description':'bounded personal operations snapshot',
                'parameters':{
                    'type':'object',
                    'properties':{
                        'day':{'type':'string'}
                    },
                    'additionalProperties':False,
                },
            }],
        }

    def retrieve_context(self,request,requirements):
        return {
            'source':'test',
            'rendered':'',
        }

    def invoke(self,tool,arguments):
        raise AssertionError(
            f'unexpected Gen-1 invocation: {tool}'
        )


class FakeOperations:
    def __init__(self):
        self.calls=[]

    def invoke(self,arguments,*,user_id):
        self.calls.append((dict(arguments),user_id))
        return {
            'output':{
                'today':{
                    'active_work':[],
                    'attention':[],
                },
                'operations':{
                    'pending_approvals':[],
                },
                'next_action':{
                    'status':'OPEN',
                    'title':'Finish the highest-priority unfinished task',
                    'source':'daily_brief',
                },
                'provenance':{
                    'bounded':True,
                },
                'owner_user_id':user_id,
            },
            'verification':{
                'verified':True,
                'method':'test bounded reread',
            },
        }


def planner_payload(arguments=None):
    return {
        'steps':[{
            'step_id':'step-1',
            'objective':'Read current personal operations',
            'required_capabilities':['operations_snapshot'],
            'depends_on':[],
            'success_criteria':['bounded snapshot verified'],
            'arguments':{} if arguments is None else arguments,
            'timeout_seconds':30,
            'retry_limit':0,
        }],
        'success_criteria':[{
            'description':'operations snapshot verified',
            'verification_method':'all_steps_verified',
        }],
        'risk':'LOW',
        'confidence':0.99,
        'unresolved_questions':[],
    }


class StaticOpsPlanner:
    def propose(self,goal,context,available_capabilities):
        proposal=PlanProposal(
            uuid.uuid4().hex,
            goal.goal_id,
            [PlanProposalStep(
                'ops',
                'Read current personal operations',
                ['operations_snapshot'],
                [],
                ['bounded snapshot verified'],
                {},
                30,
                0,
            )],
            [{
                'description':'operations snapshot verified',
                'verification_method':'all_steps_verified',
            }],
            'LOW',
            0.99,
            [],
            'test-only',
        )
        provenance=ModelProvenance(
            request_id='test',
            provider='test',
            model='test',
            capability='reasoning',
            requested_capabilities=['planning','reasoning'],
            selection_reason='test',
            health='HEALTHY',
            trace_id=None,
            fallback=False,
        )
        return proposal,provenance


class Cycle74Tests(unittest.TestCase):

    def test_operations_snapshot_visibility_and_no_preferred_tool_contract(self):
        from sparkle_gen2.gen1 import LocalGen1Gateway

        gateway=FakePlanningGateway(planner_payload())

        concrete=object.__new__(LocalGen1Gateway)
        concrete.system=gateway.system
        concrete.capability_router=None

        LocalGen1Gateway.plan(
            concrete,
            {
                'goal_id':'g',
                'user_request':(
                    'current system status and one concrete next action'
                ),
                'constraints':[],
                'deadline':None,
            },
            {
                'source':'test',
                'rendered':'',
                'tool_schemas':{
                    'operations_snapshot':{
                        'name':'operations_snapshot',
                        'description':(
                            'bounded personal operations snapshot'
                        ),
                        'parameters':{
                            'type':'object',
                            'properties':{
                                'day':{'type':'string'}
                            },
                            'additionalProperties':False,
                        },
                    }
                },
            },
            ['operations_snapshot'],
        )

        prompt=gateway.router.last_request.messages[0].content

        self.assertIn(
            'operations_snapshot',
            prompt,
        )
        self.assertNotIn(
            '"preferred_tool"',
            prompt,
        )
        self.assertIn(
            'omit day entirely',
            prompt.lower(),
        )

    def test_planner_output_parses_without_preferred_tool(self):
        from sparkle_gen2.gen1 import LocalGen1Gateway

        gateway=FakePlanningGateway(planner_payload())

        concrete=object.__new__(LocalGen1Gateway)
        concrete.system=gateway.system
        concrete.capability_router=None

        class Goal:
            goal_id='g'

            def to_dict(self):
                return {
                    'goal_id':'g',
                    'user_request':'current system status',
                    'constraints':[],
                    'deadline':None,
                }

        proposal,_=Gen1PlannerModel(concrete).propose(
            Goal(),
            {
                'source':'test',
                'rendered':'',
                'tool_schemas':{
                    'operations_snapshot':{
                        'name':'operations_snapshot',
                        'description':(
                            'bounded personal operations snapshot'
                        ),
                        'parameters':{
                            'type':'object',
                            'properties':{
                                'day':{'type':'string'}
                            },
                            'additionalProperties':False,
                        },
                    }
                },
            },
            ['operations_snapshot'],
        )

        self.assertEqual(
            proposal.steps[0].required_capabilities,
            ['operations_snapshot'],
        )
        self.assertEqual(
            proposal.steps[0].arguments,
            {},
        )

    def test_missing_required_arguments_fail_closed_before_tool_execution(self):
        proposal=PlanProposal(
            uuid.uuid4().hex,
            'g',
            [PlanProposalStep(
                'bad',
                'Inspect one connector',
                ['connector_health'],
                [],
                ['health observed'],
                {},
                30,
                0,
            )],
            [{
                'description':'verified',
                'verification_method':'all_steps_verified',
            }],
            'LOW',
            0.9,
            [],
            'test-only',
        )

        plan,_=PlanValidator(
            {'connector_health'},
            PolicyEngine(),
        ).validate(
            proposal,
            subject='user',
            timestamp='2026-09-23T00:00:00+00:00',
        )

        agent=object.__new__(PersonalAgent)

        with self.assertRaises(PlanValidationError) as cm:
            agent._validate_plan_arguments(
                plan,
                {
                    'connector_health':{
                        'name':'connector_health',
                        'parameters':{
                            'type':'object',
                            'properties':{
                                'connector_id':{
                                    'type':'string'
                                }
                            },
                            'required':['connector_id'],
                            'additionalProperties':False,
                        },
                    }
                },
            )

        self.assertIn(
            'missing_required_argument',
            str(cm.exception),
        )
        self.assertIn(
            'connector_id',
            str(cm.exception),
        )

    def test_valid_operations_snapshot_plan_executes_and_reports_grounded_next_action(self):
        operations=FakeOperations()

        with tempfile.TemporaryDirectory() as d:
            store=Gen2Store(
                Path(d)/'g2.db'
            )

            agent=PersonalAgent(
                store,
                FakeAgentGateway(),
                planner=StaticOpsPlanner(),
                operations_service=operations,
            )

            result=agent.start(
                (
                    'Give me my current system status and identify '
                    'one concrete next action.'
                ),
                user_id='user',
            )

        self.assertEqual(
            result['status'],
            'COMPLETED',
        )
        self.assertEqual(
            operations.calls,
            [({},'user')],
        )
        self.assertIn(
            'Next: Finish the highest-priority unfinished task.',
            result['text'],
        )


if __name__=='__main__':
    unittest.main()