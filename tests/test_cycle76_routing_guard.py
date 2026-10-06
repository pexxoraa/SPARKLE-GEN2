import unittest

from sparkle_gen2.models import PlanProposal, Goal
from sparkle_gen2.planner import Gen1PlannerModel


class FakeGateway:
    def __init__(self, capability):
        self.capability = capability

    def plan(self, goal, context, available_capabilities):
        return {
            "proposal": {
                "proposal_id": "route-test",
                "goal_id": goal["goal_id"],
                "steps": [{
                    "step_id": "step-1",
                    "objective": "bounded action",
                    "required_capabilities": [self.capability],
                    "depends_on": [],
                    "success_criteria": ["observable result"],
                    "arguments": {},
                    "timeout_seconds": 30,
                    "retry_limit": 1,
                }],
                "success_criteria": [{
                    "description": "goal result verified",
                    "verification_method": "all_steps_verified",
                }],
                "risk": "LOW",
                "confidence": 0.9,
                "unresolved_questions": [],
            },
            "provenance": {
                "request_id": "route-test-request",
                "provider": "nvidia",
                "model": "nvidia/nemotron-test",
                "capability": "reasoning",
                "requested_capabilities": ["planning", "reasoning"],
                "selection_reason": "test",
                "health": "HEALTHY",
                "trace_id": None,
                "fallback": False,
            },
        }


class DummyGoal:
    def __init__(self, request):
        self.goal_id = "goal-route-test"
        self.request = request

    def to_dict(self):
        return {
            "goal_id": self.goal_id,
            "user_request": self.request,
            "constraints": [],
            "deadline": None,
        }


class Cycle76RoutingGuardTests(unittest.TestCase):

    def test_personal_project_request_forces_project_search(self):
        goal = DummyGoal("Find my Python projects")

        proposal, _ = Gen1PlannerModel(
            FakeGateway("engineering_inspect")
        ).propose(
            goal,
            {},
            ["engineering_inspect", "project_search"],
        )

        step = proposal.steps[0]

        self.assertEqual(
            step.required_capabilities,
            ["project_search"],
        )
        self.assertEqual(
            step.arguments,
            {
                "query": "Find my Python projects",
                "limit": 10,
            },
        )

    def test_repository_file_listing_forces_engineering_inspect(self):
        goal = DummyGoal(
            "List the important files in my current SPARKLE-GEN2 project"
        )

        proposal, _ = Gen1PlannerModel(
            FakeGateway("project_search")
        ).propose(
            goal,
            {},
            ["engineering_inspect", "project_search"],
        )

        step = proposal.steps[0]

        self.assertEqual(
            step.required_capabilities,
            ["engineering_inspect"],
        )
        self.assertEqual(
            step.arguments,
            {"operation": "snapshot"},
        )

    def test_unrelated_request_does_not_force_route(self):
        goal = DummyGoal("What is 2 + 2?")

        proposal, _ = Gen1PlannerModel(
            FakeGateway("calculator")
        ).propose(
            goal,
            {},
            ["calculator", "engineering_inspect", "project_search"],
        )

        self.assertEqual(
            proposal.steps[0].required_capabilities,
            ["calculator"],
        )


if __name__ == "__main__":
    unittest.main()
