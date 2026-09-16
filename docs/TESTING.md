# Testing

Run the Gen-2 suite with Gen-1 importable:

```bash
PYTHONPATH=src:/home/prem-macharla/SPARKLE-level3-git/src python3 -m unittest discover -s tests -v
```

Cycle 2 acceptance covers: model-planner retry/failure, strict plan validation, duplicate IDs, dependency cycles, unresolved questions, unknown/shell capabilities, exact Gen-1 tool boundary, approval persistence, restart reconciliation, approve/reject behavior, multi-step retry, independent goal criteria, model risk-downgrade rejection, and model self-completion rejection.

The cross-process acceptance test executes step 1, persists a pending approval for step 2, reconstructs `PersonalAgent` from the same SQLite database, approves, resumes, verifies step 2, evaluates criteria, and completes.

Live provider acceptance is separate from deterministic tests. It is accepted only when Gen-1 reports an available configured provider and a real model response produces a valid structured proposal. Missing credentials or unavailable provider health is reported as a blocker, never replaced with mock evidence.


## Extended acceptance

The suite also covers context minimization, sessions, bounded background worker, proactive event filtering, connector scopes, external-provider fail-closed behavior, device/robot safety, experiments, controlled self-improvement, audit tamper detection, exact Gen-1 schema contracts, cancellation/deadlines/replanning, CLI aliases and trace IDs. Real isolated Gen-1 acceptance covers bounded file read, memory/knowledge/project/learning/research reads, memory-review reconciliation, engineering scaffold, Python compile verification and artifact packaging.
