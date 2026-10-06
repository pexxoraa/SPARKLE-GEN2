"""Agent selection boundary. Agent identity is independent from model selection."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .base import AgentRequest, AgentResponse
from ..agent_registry import AgentRegistry

@dataclass(slots=True)
class AgentRuntime:
    registry: AgentRegistry
    agents: dict[str, Any]

    def resolve(self, agent_id: str | None) -> Any:
        profile=self.registry.resolve(agent_id)
        try: return self.agents[profile.agent_id]
        except KeyError as exc: raise KeyError(f"agent_not_registered:{profile.agent_id}") from exc

    def profile(self, agent_id: str | None): return self.registry.resolve(agent_id)

    def list(self): return self.registry.list(conversation_only=True)
