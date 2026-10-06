import unittest

from sparkle_gen2.models import Goal
from sparkle_gen2.planner import Gen1PlannerModel


def payload(criteria):
    return {
        "proposal": {
            "proposal_id": "proposal-1",
            "goal_id": "wrong-goal-replaced-by-planner",
            "steps": [
                {
                    "step_id": "step-1",
                    "objective": "bounded project discovery",
                    "required_capabilities": ["project_search"],
                    "depends_on": [],
                    "success_criteria": ["observed result"],
                    "arguments": {},
                    "timeout_seconds": 30,
                    "retry_limit": 1,
                }
            ],
            "success_criteria": criteria,
            "risk": "LOW",
            "confidence": 0.9,
            "unresolved_questions": [],
        },
        "provenance": {
            "request_id": "test-request",
            "provider": "nvidia",
            "model": "nvidia/nemotron-test",
            "capability": "reasoning",
            "requested_capabilities": ["planning", "reasoning"],
            "selection_reason": "test",
            "health": "HEALTHY",
            "fallback": False,
        },
    }


class FakeGateway:
    def __init__(self, data):
        self.data = data

    def plan(self, goal, context, capabilities):
        return self.data


class Cycle75Tests(unittest.TestCase):
    def goal(self):
        return Goal(
            goal_id="goal-1",
            user_request="Find my Python projects",
            normalized_objective="Find my Python projects",
        )

    def test_extra_goal_criterion_metadata_is_discarded(self):
        gateway = FakeGateway(
            payload(
                [{
                    "description": "goal result verified",
                    "verification_method": "all_steps_verified",
                    "evidence": "model metadata",
                    "confidence": 0.99,
                }]
            )
        )

        proposal, _ = Gen1PlannerModel(gateway).propose(
            self.goal(), {}, ["project_search"]
        )

        self.assertEqual(
            proposal.success_criteria,
            [{
                "description": "goal result verified",
                "verification_method": "all_steps_verified",
            }],
        )

    def test_missing_required_goal_criterion_field_fails_closed(self):
        gateway = FakeGateway(
            payload([{
                "description": "goal result verified",
            }])
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "planner_goal_criterion_missing_required_field",
        ):
            Gen1PlannerModel(gateway).propose(
                self.goal(), {}, ["project_search"]
            )

    def test_invalid_goal_criterion_description_fails_closed(self):
        gateway = FakeGateway(
            payload([{
                "description": "   ",
                "verification_method": "all_steps_verified",
            }])
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "planner_goal_criterion_invalid_description",
        ):
            Gen1PlannerModel(gateway).propose(
                self.goal(), {}, ["project_search"]
            )


if __name__ == "__main__":
    unittest.main()
