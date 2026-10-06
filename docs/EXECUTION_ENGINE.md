# Persistent execution engine

The production path is ConversationService → PersonalAgent → ExecutionLifecycleService → capability validation → deterministic permissions/risk → persisted approval → ToolDispatcher → native/environment adapter → independent observation verification → goal criteria → memory proposals. `runtime.py` assembles this path. Compatibility imports and CLI entry points delegate to the same services.

## Durable state and controls

Goals, proposals, plans, TaskRuns, criteria, permissions, risk evaluations, approvals, model provenance, events, recovery history and operation traces are SQLite records. TaskRun JSON additions have defaults, so existing databases remain readable. New execution-lease and personal-graph tables are additive migrations.

Pause and cancellation requests are settings persisted independently from the currently running worker's object. They are checked before execution, between steps, after adapter return and during persistence. A paused run survives reconstruction. Resuming skips VERIFIED steps. Cancellation during a blocking adapter stops subsequent steps after the adapter returns.

The per-goal SQLite lease uses an immediate transaction and PID/process-birth identity. Concurrent resumes cannot execute the same goal twice. A dead-process lease can be reclaimed. An interrupted EXECUTING write becomes `INTERRUPTED_ACTION`; a caller must inspect its effects and choose an explicit new plan before another state-changing attempt. Read-only retries require an ALLOW policy decision and remain bounded by persisted attempt/resource limits. Production enables automatic safe retries; the compatibility agent constructor preserves its explicit `auto_retry` option.

A missing provider/context produces persisted WAITING state with no tool execution. A later retry replans the same goal and preserves its history and consumed budgets. Captured manual tasks require explicit planning. Provider exceptions expose a bounded error type/category/retryable flag, not the raw private diagnostic.

## Bounds and measured usage

The engine checks cumulative action iterations, measured active runtime, planning-call count, deadlines and step retries across all runs for a goal. Planning defaults to at most eight calls; runtime and iteration ceilings are constructor configuration. `ResourceBudget` accepts named limits and measured usage. Provider-reported token counts are retained when available; unknown usage is `None`, never estimated as a verified count. An explicit token ceiling fails closed before model work when a trustworthy reservation is unavailable.

Step deadlines are checked after a synchronous adapter returns. Gen-2 does not forcibly kill arbitrary native calls in another process. Provider/connector adapters enforce their own transport deadlines. A late return becomes `ACTION_TIMEOUT` and is not blindly retried; active runtime still includes the call. This is cooperative cancellation and timeout handling, not preemptive process isolation.

## Typed tools and capabilities

`domain/contracts/tool_protocol.py` defines ToolDefinition, ToolInput, ToolOutput, ToolError, ToolMetadata, PermissionMetadata, RiskMetadata and VerificationMetadata. ToolInput correlates owner, goal, run, step, tool and arguments. The dispatcher rejects mismatched envelopes. Typed success requires a successful observation, verified evidence and no pending approval.

Schema validation covers JSON object/array/string/number/integer/boolean/null types, required/additional properties, enums, ranges, finite numbers, lengths and patterns. It limits recursion, node count and collection size. Failures identify the schema location without echoing argument values. Plan validation checks bounded step counts, capability identity, dependency cycles and unresolved questions, and topologically orders valid dependencies before execution.

The capability catalog uses real native/environment definitions, supported profiles/models, permissions, risk, availability and execution-handler metadata. Agent profiles are separate from provider/model identity. Selecting a specialist preserves the user's request and supplies the profile to planning. Structured `AgentResult` and existing delegation records carry results, evidence, errors, recommendations, artifacts and next actions. Native specialist writes still require the established exact approval/grant boundary.

## Independent verification

The adapter's independently observed contract must pass before a step verifier accepts the result. Supported strategies include returned value, expected state, HTTP status, file existence, database state, command result, test result and artifact existence. Expected values are compared against bounded paths in the already observed result. Gen-2 does not grant a verifier arbitrary filesystem, command, database or network access from a model-supplied path.

Custom and semantic verifiers must be explicitly registered trusted handlers. An absent handler or unsupported strategy blocks validation; semantic success is not fabricated. `{}` retains the adapter's existing independent verification contract. Native durable writes use actual persistent-record/file-digest rereads, connector writes use the corresponding provider reread, and robotics uses the independent safety/observation boundary.

All steps must be VERIFIED and all persisted goal criteria SATISFIED before completion. A successful bounded child execution updates its execution record and graph; it does not prove completion of a larger project or long-term goal. Rollback continues through the existing approval-controlled, evidence-verified rollback service.

## Evidence

`test_execution_completion.py` covers native-tool conversation execution, autonomous safe retry, restart-safe pause/resume, in-flight cancellation, cumulative budgets, concurrent resume, interrupted writes, topological dependencies, provider/context recovery and private-error exclusion. `test_tool_protocol_completion.py` covers typed/schema/verification/resource contracts. Existing approval, delegation, workspace-isolation, background-worker, risk and cross-domain suites remain required regressions. Real provider/hardware acceptance is separate from deterministic or injected-transport tests.
