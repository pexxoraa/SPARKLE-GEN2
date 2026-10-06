"""Small contracts shared by all SPARKLE agents."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class AgentRequest:
    text: str
    user_id: str = "user"
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResponse:
    text: str
    status: str = "COMPLETED"
    agent_id: str = "personal"
    data: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    """Minimum contract for a SPARKLE agent."""

    agent_id: str

    def respond(self, request: AgentRequest) -> AgentResponse: ...
