"""Small contracts shared by all SPARKLE agents."""

from dataclasses import asdict, dataclass, field
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


@dataclass(slots=True)
class AgentResult:
    success: bool
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    confidence: float | None = None

    def to_dict(self):return asdict(self)

    @classmethod
    def from_report(cls, report):
        status=str(report.get('status','FAILED'))
        return cls(status=='COMPLETED',status,str(report.get('text','')),
                   data={k:report.get(k) for k in ('goal_id','task_run_id','trace_id','criteria')},
                   artifacts=list(report.get('artifacts') or []),observations=list(report.get('verified') or []),
                   next_actions=['review_approvals'] if report.get('approvals') else (['inspect_execution'] if status in {'BLOCKED','FAILED','WAITING'} else []))


class Agent(Protocol):
    """Minimum contract for a SPARKLE agent."""

    agent_id: str

    def respond(self, request: AgentRequest) -> AgentResponse: ...
