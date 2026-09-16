# Roadmap

## Completed foundation

- Cycle 1: separate repository, Gen-1 gateway, persistent Goal/Plan/TaskRun, bounded execution, verification, restart recovery.
- Cycle 2: provider-neutral model planner boundary, structured PlanProposal, deterministic validation, persistent permission/risk/approval/criteria/provenance, approval restart reconciliation, planner recovery, independent goal evaluation, security acceptance.
- Cycle 3: personal context selection, persistent sessions, bounded background task control, restart recovery, and relevance-filtered proactive events.
- Later software cycles: typed connectors/tools, persistent world model, cross-domain verified completion, approval-safe engineering orchestration, multimodal/voice/device/robot safety harnesses, experiments, audit, rollback, diagnostics, daily OS and controlled self-improvement.

## External acceptance blocker

Live Nemotron planning requires a configured Gen-1 provider credential. The current host reports the Nemotron route unavailable and has no live credential configured, so live-provider acceptance remains open. Mocked evidence is not substituted.

## Terminal classification

All currently declared roadmap surfaces are tracked in `default_acceptance.py`. Software-completable core surfaces are verified; account/provider/device-dependent surfaces are externally blocked; production deployment is deferred pending target selection. Future work should move an external capability to LIVE_VERIFIED only after genuine provider/account/device acceptance.
