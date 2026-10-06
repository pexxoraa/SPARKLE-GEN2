# Agent model

The user interacts with one `PersonalAgent`. Model output is a proposal, never authority. The agent persists Goal, Plan, TaskRun, success criteria, approvals and evidence; deterministic policy and Gen-1 remain authoritative for execution.
Each task run also carries a durable correlation trace ID; bounded operation spans are persisted without prompts, hidden reasoning, credentials or raw tool arguments.

Trusted flow: understand → bounded context → planner proposal → validation → policy/risk/permission → approval → Gen-1 execution → observation → independent verification → goal evaluation → persistence/memory.

## Specialist delegation

`PersonalAgent` remains the only Gen-2 coordinator. A validated plan may use the synthetic `specialist_delegate` capability when the configured Gen-1 gateway exposes its certified `AgentRegistry` and `Orchestrator.run_multi` boundary. Gen-2 does not create another agent registry or executor.

Delegation is optional. Simple goals continue through direct bounded tools; specialist work is selected only by the PersonalAgent plan when multiple perspectives or specialized analysis are useful. Every delegation keeps the parent `goal_id`, `task_run_id`, Gen-2 `trace_id`, and persisted `user_id`.

Gen-2 permits read-only delegation directly and permits only explicitly supported write actions through the trusted scoped-grant boundary below. Approval-required or unknown specialist tools remain hidden unless a server-side grant implementation exists for that exact tool; model-generated `approved=true` arguments never become authorization.

### Approval-aware specialist grants

A plan may request a write-capable specialist action, but planner fields and model tool arguments never grant authority. `PersonalAgent` first persists the delegation and creates a normal Gen-2 `Approval` whose requested scope binds the authenticated user, parent goal/task/delegation, specialist, capability/tool, and exact approved action arguments. Only a trusted human approval can mint a `DelegationGrant`; model/system identities cannot issue one.

The grant is persisted, time-bounded, integrity-fingerprinted, and one-shot. At execution time Gen-2 constructs an isolated instance of the existing Gen-1 `Orchestrator` with the same registry/router/context/traces/budgets but an authorization-enforcing tool proxy. The proxy hides ungranted write tools and consumes the authoritative server-side grant before forwarding the exact approved action to Gen-1 `ToolRegistry.execute`. Model-supplied `approved`, approval IDs, grant IDs, or prose are ignored as authority.

Supported write-capable specialist grants are `memory_write`, narrowly bounded `workspace_scaffold`, bounded `workspace_verify`, and bounded `workspace_package`. Workspace operations are restricted to the `application_builder` specialist. `workspace_scaffold` requires a brand-new lowercase project, `overwrite=false`, and an exact approved UTF-8 file manifest; `workspace_verify` binds the exact project and ordered static/compile check list; `workspace_package` binds exactly one approved project identity. Package completion requires Gen-2 to reread the persisted artifact record, current source workspace digest, immutable artifact path, ZIP digest, and deterministic source manifest relationship. `workspace_test` and `agent_install` remain nondelegable.

## Perception-grounded robot context

Robot-state questions may use `perception_observe`, which obtains a fresh registered source observation, normalizes/persists it, performs bounded same-robot fusion, updates the existing world model, and returns only freshness/provenance-backed state. PersonalAgent does not infer a current robot pose from stale persisted state. Motion remains a separate approval-required action and requires fresh perception when the integrated perception service is configured.


## Structured profiles and results

The registry includes the sixteen actual native specialist names and bounded Gen-2 profiles, while PersonalAgent remains the coordinator. A selected profile is persisted independently of the user's request, reaches planner context and determines the coordinating agent identity on validated steps. AgentResult carries success/status/summary/data/artifacts/observations/recommendations/errors/next_actions/confidence. Native specialist delegation still uses the existing typed request/result, bounded multi-agent orchestration, exact grants and persistent trace rereads.

Agent Builder creates native installed definitions; AI/Application builders reuse native structured specifications, workspace artifacts and controlled testing/install boundaries. Deployment to a new remote target remains a separate authorized environment action. Registration/profile availability alone is not fresh acceptance of every possible generated application.
