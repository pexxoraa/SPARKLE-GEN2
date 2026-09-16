# Orchestration

Gen-2 owns goal orchestration. It supports bounded continuation, retry, cancellation, deadline blocking, approval waits, restart recovery and replanning. Replanning cannot proceed around a pending approval. Background work uses persistent tasks and a bounded worker pass; service scheduling is deployment-owned.

Proactive orchestration is bounded as event -> relevance -> minimal context -> decision -> deterministic policy -> action/notification. Low-relevance events are dropped before context/decision work, and policy denial yields no action.
