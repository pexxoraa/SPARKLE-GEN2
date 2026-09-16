# Architecture

## Dependency boundary

`PersonalAgent` depends on `Gen1Gateway`. `LocalGen1Gateway` consumes Gen-1 `SparkleSystem.context`, `SparkleSystem.model_router`, and `SparkleSystem.tools`; it does not copy provider adapters, ToolRegistry, stores, workers, authentication, or secrets.

## Cycle 2 trusted pipeline

1. Persist Goal and retrieve bounded relevant Gen-1 context.
2. `PlannerModel` requests a provider-neutral planning operation over Gen-1's supported reasoning route.
3. Persist strict `PlanProposal` and actual model/provider provenance.
4. `PlanValidator` checks schema, step IDs, dependencies/cycles, capabilities, criteria, timeout/retry bounds, and unresolved questions.
5. `PolicyEngine` deterministically produces persistent Permission and RiskEvaluation objects.
6. State-changing capabilities require persistent user Approval before execution.
7. Capability resolves exactly to a registered Gen-1 tool and executes through Gen-1 ToolRegistry with an exact allow-set.
8. Gen-1 observation is independently verified; model assertions are not verification evidence.
9. `GoalSuccessCriterion` objects are evaluated by deterministic methods, including persisted-plan and verified-step evidence.
10. Goal completion requires every executable step VERIFIED and every required criterion SATISFIED.

## Model authority boundary

The model may propose steps, dependencies, capabilities, arguments, and candidate success criteria. It cannot mutate policy, grant permissions, approve actions, invoke tools directly, mark verification true, or set final completion state.
