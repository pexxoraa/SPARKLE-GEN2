from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentProfile:
    agent_id: str
    name: str
    description: str
    category: str
    capabilities: tuple[str, ...] = ()
    specialist_names: tuple[str, ...] = ()
    preferred_model_capabilities: tuple[str, ...] = ("planning", "reasoning")
    conversation_enabled: bool = True
    planning_enabled: bool = True
    execution_enabled: bool = False
    system_agent: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["capabilities"] = list(self.capabilities)
        value["specialist_names"] = list(self.specialist_names)
        value["preferred_model_capabilities"] = list(self.preferred_model_capabilities)
        return value


class AgentRegistry:
    """First-class SPARKLE agent catalog, separate from provider/model routing."""

    def __init__(self, profiles: list[AgentProfile] | None = None):
        self._profiles: dict[str, AgentProfile] = {}
        for profile in profiles or self.default_profiles():
            self.register(profile)

    @staticmethod
    def default_profiles() -> list[AgentProfile]:
        return [
            AgentProfile(
                "personal", "Personal", "General personal assistant and system coordinator.",
                "core", ("conversation", "memory", "context", "planning"), system_agent=True,
            ),
            AgentProfile(
                "research", "Research", "Research planning, evidence synthesis, experiments, and documentation.",
                "knowledge", ("research_workspace", "research_pipeline", "experiments", "retrieval"),
                ("research",),
            ),
            AgentProfile(
                "learning", "Learning", "Learning plans, assessments, mastery tracking, and weak-area retraining.",
                "knowledge", ("learning_plan_create", "learning_assess", "learning_progress", "skills"),
                ("learning",),
            ),
            AgentProfile(
                "engineering", "Engineering", "Software engineering, repository analysis, implementation and verification.",
                "build", ("engineering_inspect", "workspace_scaffold", "workspace_verify", "workspace_package"),
                ("application_builder", "software_engineering"),
                ("planning", "reasoning"), execution_enabled=True,
            ),
            AgentProfile(
                "projects", "Project", "Project planning, milestones, dependencies, and execution coordination.",
                "execution", ("project_search", "project_tasks", "planning"),
                ("project",),
            ),
            AgentProfile(
                "skills", "Skills", "Skill progression, evidence, assessment, and capability graph management.",
                "knowledge", ("skills", "learning_progress", "assessment"),
                ("skill",),
            ),
            AgentProfile(
                "automation", "Automation", "Scheduled workflows, recurring work, conditions, and background execution.",
                "execution", ("automation_create", "automation_run", "background"),
                ("automation",),
                execution_enabled=True,
            ),
            AgentProfile(
                "robotics", "Robotics", "Robot perception, ROS2 workflows, simulation, and verified motion planning.",
                "build", ("perception_observe", "ros2", "robotics"),
                ("software_engineering", "research", "learning"),
                execution_enabled=True,
            ),
            AgentProfile(
                "device", "Device", "Authorized computer, Linux, mobile, and device-side operations.",
                "system", ("device_management", "computer", "linux", "mobile"),
                ("system",),
                execution_enabled=True,
            ),
            AgentProfile(
                "analyst", "Analyst", "Structured data analysis, comparison, diagnosis, and decision support.",
                "knowledge", ("retrieval", "analysis", "comparison"),
                ("data_analysis",),
            ),
            AgentProfile('exam','Exam','Syllabus, timed practice, mock tests and error analysis.','knowledge',('learning_progress','skill_search','knowledge_search'),('exam',)),
            AgentProfile('coding','Coding','Implement, debug, test and review software.','build',('engineering_inspect','workspace_verify'),('coding',),execution_enabled=True),
            AgentProfile('software_engineering','Software Engineering','Architecture, implementation, regression and release verification.','build',('engineering_inspect','workspace_verify','workspace_package'),('software_engineering',),execution_enabled=True),
            AgentProfile('application_builder','Application Builder','Requirements through implementation, tests and packaged application artifacts.','build',('workspace_scaffold','workspace_verify','workspace_package'),('application_builder',),execution_enabled=True),
            AgentProfile('ai_builder','AI Builder','Provider-independent AI system architecture and implementation.','build',('workspace_scaffold','workspace_verify','workspace_package'),('ai_builder',),execution_enabled=True),
            AgentProfile('agent_builder','Agent Builder','Design, build, test and register modular agents.','build',('agent_install','workspace_verify'),('agent_builder',),execution_enabled=True),
            AgentProfile('content','Content','Research, scripts, production plans and content iterations.','knowledge',('content_search','knowledge_search'),('content',)),
            AgentProfile('productivity','Productivity','Priorities, deadlines, schedules and actionable work.','execution',('project_search','project_tasks','daily_brief_generate'),('productivity',)),
            AgentProfile('system','System','Evidence-backed configuration, runtime and health diagnostics.','system',('operations_snapshot','engineering_inspect'),('system',),system_agent=True),
        ]

    def register(self, profile: AgentProfile) -> AgentProfile:
        key = str(profile.agent_id).strip().lower()
        if not key or key != profile.agent_id:
            raise ValueError("agent_id must be a normalized non-empty string")
        if key in self._profiles:
            raise ValueError(f"duplicate agent: {key}")
        self._profiles[key] = profile
        return profile

    def get(self, agent_id: str) -> AgentProfile:
        key = str(agent_id or "").strip().lower()
        if key not in self._profiles:
            raise KeyError(key)
        return self._profiles[key]

    def list(self, *, conversation_only: bool = False) -> list[dict[str, Any]]:
        profiles = list(self._profiles.values())
        if conversation_only:
            profiles = [p for p in profiles if p.conversation_enabled]
        return [p.to_dict() for p in profiles]

    def specialists_for(self, agent_id: str) -> list[str]:
        return list(self.get(agent_id).specialist_names)

    def capabilities_for(self, agent_id: str) -> list[str]:
        return list(self.get(agent_id).capabilities)

    def resolve(self, agent_id: str | None) -> AgentProfile:
        aliases={'skill':'skills','project':'projects','data_analysis':'analyst'}
        return self.get(aliases.get(agent_id,agent_id) or "personal")

    def snapshot(self) -> dict[str, Any]:
        return {"agents": self.list(), "default_agent_id": "personal"}
