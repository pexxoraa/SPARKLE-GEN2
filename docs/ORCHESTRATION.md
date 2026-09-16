# Orchestration

Gen-2 owns goal orchestration. It supports bounded continuation, retry, cancellation, deadline blocking, approval waits, restart recovery and replanning. Replanning cannot proceed around a pending approval. Background work uses persistent tasks and a bounded worker pass; service scheduling is deployment-owned.
