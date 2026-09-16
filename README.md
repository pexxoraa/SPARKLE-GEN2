# SPARKLE Gen-2

SPARKLE Gen-2 is a separate personal-agent application built on the certified SPARKLE Gen-1 platform. It does not copy, replace, or silently modify Gen-1.

## Cycle 2 architecture

`user goal → bounded Gen-1 context → model plan proposal → deterministic validation → Gen-2 policy/risk/approval → exact Gen-1 tool → independent observation/verification → goal criteria → natural response`

Production planning uses `Gen1PlannerModel`, which asks Gen-1's provider-neutral `ModelRouter` for the supported `reasoning` capability while recording that the planner operation requires `planning + reasoning`. Gen-2 never hard-codes Nemotron; actual provider/model provenance is persisted.

Model output is only a proposal. It cannot grant permission, approve actions, execute tools, change risk policy, verify its own effects, or declare a goal complete.

## Run

Gen-1 must be importable. During development:

```bash
export PYTHONPATH=/home/prem-macharla/SPARKLE-GEN2/src:/home/prem-macharla/SPARKLE-level3-git/src
python -m sparkle_gen2.cli "Organize my Python learning for this week"
```

Use `--json` for structured diagnostics and `--verbose` for concise progress. Resume with `--resume GOAL_ID`. Resolve a Gen-2 approval with `--approve APPROVAL_ID` or `--reject APPROVAL_ID`.

## Persistence and security

Gen-2 persists goals, plan proposals, validated plans, task runs, permissions, risk evaluations, approvals, success criteria, model provenance, and lifecycle events in its own SQLite store. Approval and execution state survive process restart.

Gen-1 remains authoritative for model/provider runtime, ToolRegistry, execution boundaries, worker isolation, security, cancellation, and Gen-1 authorization. Capability resolution is exact: unsupported capabilities fail closed and are never silently substituted.

## Current boundary

Cycle 2 implements model-assisted planning, deterministic plan validation, permission/risk/approval policy, restart-safe approval reconciliation, independent goal evaluation, planner failure recovery, natural CLI reporting, and security acceptance tests. Background jobs, proactive events, full session continuity, connectors, voice, GUI, IoT, and robotics are deferred to later cycles.
