# Agent model

The user interacts with one `PersonalAgent`. Model output is a proposal, never authority. The agent persists Goal, Plan, TaskRun, success criteria, approvals and evidence; deterministic policy and Gen-1 remain authoritative for execution.

Trusted flow: understand → bounded context → planner proposal → validation → policy/risk/permission → approval → Gen-1 execution → observation → independent verification → goal evaluation → persistence/memory.
