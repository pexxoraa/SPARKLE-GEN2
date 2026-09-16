# Architecture

## Product architecture

SPARKLE Gen-2 is one persistent Personal Core with multiple authenticated presentation/device clients. `sparkle-personal-core` serves the responsive PWA and the private API. `sparkle-background-worker` resumes persistent background tasks. The CLI remains an administration, recovery, and engineering interface over the same underlying services.

The Personal Core owns shared sessions, conversation history, goals, plans, task runs, approvals, notifications, device identities, world state, deterministic retrieval plus optional externally-blocked semantic interfaces, research/experiments, artifacts, and lifecycle evidence. Devices receive only policy-appropriate scoped state rather than copies of the complete private database.

## Dependency boundary

`PersonalAgent` depends on the `Gen1Gateway` protocol. `LocalGen1Gateway` consumes Gen-1 `SparkleSystem.context`, provider-neutral model routing, and ToolRegistry. `EnvironmentGateway` may add explicitly configured, typed Gen-2 environment capabilities while delegating every Gen-1 capability unchanged. Gen-2 does not copy provider secrets, Gen-1 stores, or worker authentication.

## Trusted execution pipeline

1. Persist a Goal and retrieve bounded relevant context.
2. A provider-neutral planner proposes a strict plan and arguments using only advertised typed capability schemas.
3. Persist model/provider provenance.
4. `PlanValidator` checks schema, capabilities, dependencies, criteria, bounds, and unresolved questions.
5. `PolicyEngine` deterministically produces persistent Permission and RiskEvaluation objects.
6. Approval-required actions stop before execution until a human decision is persisted.
7. Execute through the exact Gen-1 or configured Gen-2 environment capability boundary.
8. Observe the result and independently verify it; provider/model completion claims are not evidence.
9. Evaluate persisted goal criteria deterministically.
10. Mark completion only when every executable step is VERIFIED and every criterion is SATISFIED.

## Model authority boundary

Models may propose plans and candidate arguments. Models cannot add capabilities, grant or revoke permissions, approve actions, downgrade risk, bypass device scopes, invoke raw motor/GPIO/shell interfaces, self-verify effects, or set final completion state.

## Device and network boundary

Device enrollment uses one-time expiring codes and hashed random credentials. Browser credentials use HttpOnly SameSite cookies; device agents may use bearer credentials. Revocation invalidates all tokens for a device. The Personal Core defaults to loopback and requires TLS for non-loopback binding. Public deployment remains deferred.

See `PERSONAL_CORE_UI.md`, `SECURITY.md`, `INTERACTIONS.md`, `MOBILE.md`, and `ROBOTICS.md` for boundary-specific details.

## Nemotron-only model boundary

Gen-2 constructs `SparkleSystem` with `src/sparkle_gen2/nemotron_models.json`, which has one enabled model record and no fallback. The underlying router abstraction remains provider-neutral for engineering flexibility, but no second AI provider is registered in this release.
