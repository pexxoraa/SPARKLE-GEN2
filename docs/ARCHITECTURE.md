# Architecture

## Dependency boundary

`PersonalAgent` depends on the `Gen1Gateway` protocol. The current `LocalGen1Gateway` consumes the supported `SparkleSystem.context` and `SparkleSystem.tools` surfaces. Gen-2 does not copy Gen-1 stores, auth, providers, workers, or tool implementations.

## First slice flow

1. Create and persist a Goal.
2. Retrieve bounded relevant context through Gen-1.
3. Create and persist a Plan and TaskRun.
4. Select one typed Gen-1 tool from a conservative deterministic planner.
5. Execute through Gen-1's ToolRegistry with an exact allow-set.
6. Observe and verify the result.
7. Persist VERIFIED, WAITING, or BLOCKED state.
8. Return a human-readable response.

Completion is only possible when every plan step is VERIFIED. A failed or unavailable tool never becomes success.
