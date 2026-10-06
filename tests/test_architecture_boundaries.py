from sparkle_gen2.agent_registry import AgentRegistry
from sparkle_gen2.agents.router import AgentRuntime
from sparkle_gen2.domain.entities import Goal, Plan, TaskRun
from sparkle_gen2.domain.value_objects import GoalStatus, RiskLevel
from sparkle_gen2.domain.errors import SparkleError
from sparkle_gen2.infrastructure.persistence import Gen2Store
from sparkle_gen2.infrastructure.providers import ModelCapabilityManager


def test_agent_registry_is_independent_from_model_selection():
    registry = AgentRegistry()
    profile = registry.resolve("robotics")
    assert profile.agent_id == "robotics"
    assert "robotics" in profile.capabilities
    assert profile.preferred_model_capabilities


def test_agent_runtime_resolves_agents_by_identity():
    registry = AgentRegistry()
    marker = object()
    runtime = AgentRuntime(registry=registry, agents={"personal": marker})
    assert runtime.resolve("personal") is marker


def test_domain_public_api_exposes_core_types():
    assert GoalStatus.CREATED.value == "CREATED"
    assert RiskLevel.CRITICAL.value == "CRITICAL"
    assert Goal.__name__ == "Goal"
    assert Plan.__name__ == "Plan"
    assert TaskRun.__name__ == "TaskRun"
    assert issubclass(SparkleError, Exception)


def test_infrastructure_public_api_exposes_implementations():
    assert Gen2Store.__name__ == "Gen2Store"
    assert ModelCapabilityManager.__name__ == "ModelCapabilityManager"
