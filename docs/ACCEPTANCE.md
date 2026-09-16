# Acceptance

The executable source of truth is `build_acceptance_matrix()` in `default_acceptance.py`. Tests require every declared capability to be terminally classified as `LIVE_VERIFIED`, `EXTERNALLY_BLOCKED`, or `DEFERRED`; ambiguous states such as PARTIAL are invalid.

## Verified software/core

PersonalAgent lifecycle, planning validation, deterministic policy, approvals, real Gen-1 approval reconciliation, goal evaluation, context selection, persistence/restart, sessions, bounded background execution, proactive filtering, Gen-1 personal-data reads, audit, model routing/failure recovery, connector manager, natural CLI, local dashboard, notifications, world model/graph, experiments, rollback, controlled self-improvement and real isolated Gen-1 scaffold/compile/package are verified.

## Externally blocked

Live model planning; embedding/reranking/image/safety-model providers; semantic multimodal providers; STT/TTS; Gmail/Outlook/Calendar/Drive/GitHub account authorization; browser/GUI/Linux control targets; mobile; ESP32/MQTT; ROS2/robot hardware; dedicated Gen-1 workspace-test worker; and noninteractive GitHub push authentication. Each has a software harness and an explicit dependency.

## Deferred

Production deployment is deferred because no deployment target/runtime was specified.
