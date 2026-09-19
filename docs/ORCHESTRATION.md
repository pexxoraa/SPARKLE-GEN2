# Orchestration

Gen-2 owns goal orchestration. It supports bounded continuation, retry, cancellation, deadline blocking, approval waits, restart recovery and replanning. After retry exhaustion, a recovery decision may trigger a bounded automatic replan (one by default); the replacement plan still passes normal context retrieval, validation, policy, approval and verification gates. Replanning cannot proceed around a pending approval, and the replan budget prevents loops. Background work uses persistent tasks and a bounded worker pass; service scheduling is deployment-owned.

Proactive orchestration is bounded as event -> relevance -> minimal context -> decision -> deterministic policy -> action/notification. Low-relevance events are dropped before context/decision work, and policy denial yields no action.
Operation traces are persisted in the Gen-2 store and correlated by the `TaskRun.trace_id`. The Personal Agent records bounded metadata for goal creation, context retrieval, planning, action, observation, verification, recovery and completion. Trace records intentionally exclude prompts, hidden reasoning, credentials and raw tool arguments, and can be recovered after restart.

After deterministic completion, the Personal Agent may stage conservative memory candidates from explicit durable user statements. Candidate staging is idempotent and does not write memory; human approval submits through Gen-1 memory review, and reconciliation links any approved Gen-1 memory ID back to its goal/task/trace provenance.

## Bounded specialist orchestration

A `specialist_delegate` plan step is persisted before execution as a typed delegation request containing request/goal/task/trace identity, user identity, explicit specialist names, objective, bounded inputs/constraints, deadline, risk, and required evidence. Specialist names must be unique and exist in the current Gen-1 `AgentRegistry`. Gen-2 preserves Gen-1's configured limits: at most 4 specialists, 16 shared tool calls, 4 tool rounds, and 300 seconds wall-clock on the current certified boundary.

Execution terminates at Gen-1 `Orchestrator.run_multi`. Gen-1 propagates the same `user_id` to each specialist and, for multi-specialist work, to the final `personal` synthesis. Gen-2 rereads Gen-1's persistent traces and requires a successful trace for every requested specialist, a successful synthesis trace when more than one specialist is used, no unresolved Gen-1 memory-review proposal, and no requested tool outside each specialist's declared allowlist. A final model answer alone is not verification.

For sequential specialist plan steps, only verified findings/evidence from declared dependency steps are attached as bounded inputs to the later delegation. Specialists do not recursively invoke each other, so agent-to-agent loops remain bounded by the parent Gen-2 plan.

Delegation failure re-enters the normal PersonalAgent failure classifier/retry/replan path and never marks the goal complete without verified evidence. Pending delegation records survive restart and can be executed after restart. Gen-1 `run_multi` itself is synchronous and exposes no resumable in-flight token: if a process restarts while a delegation is recorded `RUNNING`, Gen-2 marks that boundary blocked rather than inventing resumability. Cancellation is enforceable before start; a cancellation requested during the synchronous call causes the returned result to be discarded, but the current Gen-1 API cannot interrupt the already-running model call.

### Scoped delegation authorization

Write-capable delegation adds two explicit authorization stages without changing existing read-only `run_multi` callers. First, Gen-2 creates an `Approval` for one exact delegated action. After trusted approval, Gen-2 issues a `DelegationGrant` containing `grant_id`, `user_id`, `goal_id`, `task_run_id`, delegation request ID, approved capability, specialist/tool allowlists, exact action scope, risk, approval ID, issuer, issue/expiry times, and one-shot usage state. The grant references the authoritative Approval rather than replacing it.

Validation reloads the Approval from the Gen-2 store, verifies user/goal/task/delegation/specialist/tool/capability/action bindings, checks expiry and an immutable-binding fingerprint, and atomically consumes the one allowed use. Reuse is denied. A persisted active grant survives restart only until its original expiry; restart never renews authority. Cancelling a pending delegation revokes an active grant.

For an approved write delegation, Gen-2 creates a per-request Gen-1 `Orchestrator` using the existing Gen-1 model router, AgentRegistry, AgentRouter, context builder, TraceStore, and certified limits. Only its tool object is replaced with a Gen-2 authorization proxy; the shared Gen-1 orchestrator and every existing `run_multi(...)` caller remain unchanged. The proxy still honors the specialist AgentSpec allowlist and exposes read-only tools normally, but exposes the approved write tool only when the persisted grant is valid for that specialist.

`memory_write`, `workspace_scaffold`, `workspace_verify`, and `workspace_package` are the currently grantable write tools. A learning specialist may submit the exact approved memory proposal, after which the parent goal waits for the existing Gen-1 memory review. For workspace operations, only `application_builder` is grantable. `workspace_scaffold` binds the complete normalized file manifest and requires a new project with `overwrite=false`; `workspace_verify` binds the exact approved project/check sequence; `workspace_package` accepts only the approved `project_name` because the current Gen-1 package contract has no caller-controlled destination or format. Before Approval is created, Gen-2 independently computes and stores the source-workspace identity (`source_digest`, file count, and byte count) in trusted approval scope. The same identity is recomputed immediately before one-shot grant consumption, so a workspace changed after approval is denied without consuming authority. After packaging, Gen-2 independently rereads the persisted artifact record and immutable ZIP, recomputes the current source-workspace digest again, and requires artifact/source digests, project relationship, deterministic `zip-stored` manifest, file count, and byte totals to agree before the parent step can verify.

`workspace_test` and `agent_install` remain blocked from specialist grants. They require their own exact scoped authorization plus independent post-action verification before Gen-2 will delegate them.

## Automation lifecycle

Automation creation is a first-class PersonalAgent action rather than a direct worker command. A validated plan may request `automation_create`; deterministic Gen-2 policy marks the operation approval-required, and the Approval scope binds user, goal, exact automation tool, and exact arguments. Only after trusted approval does Gen-2 create the authoritative Gen-1 automation record plus its Gen-2 ownership/correlation binding. Model-supplied approval fields are rejected before authority is created.

The automation object presented by Gen-2 combines authoritative Gen-1 schedule/condition/action/next-run/last-run state with Gen-2 owner, source-goal, risk, required model capabilities, linked goal/background task, last result, and verification state. Controls are `create`, `inspect`, `pause`, `resume`, `cancel`, and scheduled `run-now`; run-now is deliberately unavailable for condition automations because a condition run requires real trigger evidence. Owner identity is checked before any control mutation.

Automation execution reuses Gen-1 reliable claims/leases/cooldowns/run history and Gen-2 background continuation. Gen-2-created agent automations use exactly one outer automation attempt: retry/replan belongs to the launched PersonalAgent goal, preventing whole-goal replay after partial side effects. Relevant completion/failure notifications are emitted through the existing notification center. Duplicate condition observations are suppressed by the lower cooldown/claim state, and completed one-shot automations are not re-executed by simple re-observation.

## Perception/action loop

Integrated robotics orchestration follows `observe → normalized perception → world state → approved action → independent ROS2 verification → observe again`. `perception_observe` is read-only. `ros2_sim_move` remains approval-required and, when the perception service is present, fails closed unless `turtle1` has a fresh current perception state. The action still passes through the independent ROS2 safety controller and existing verifier; perception never grants authority.

## Daily operating loop

Daily OS provides `daily_brief_generate`/`inspect` as bounded read/derived operations and approval-gated `daily_brief_update`/`close` controls. The brief is planning context, not authority: acting on a priority still creates or continues a normal PersonalAgent goal and passes ordinary permissions, approvals, execution, observation, and verification. Recurring delivery uses the existing automation subsystem.

## Attention orchestration

Background and automation completion/failure producers now feed the existing NotificationCenter through `NotificationIntelligenceService`. The layer performs deterministic relevance, deduplication, grouping, attention-budget and escalation decisions; it does not schedule work or replace the proactive engine. `ProactiveEventEngine` remains the event→relevance→context→policy boundary, and `process_proactive()` consumes its persisted `READY/NOTIFY` result as a notification candidate.
