# Completion audit — 2026-10-06

> Historical scope and evidence. The current 44-section final live acceptance directive is audited in [FINAL_LIVE_ACCEPTANCE_2026-10-07.md](FINAL_LIVE_ACCEPTANCE_2026-10-07.md). Its software counts, current external dependencies, and verdict supersede this report. Missing earlier original documents are not a blocker for that current directive.

Full specification sign-off is BLOCKED. The attached 75-section master directive is available; the two named originals are not:

1. SPARKLE — PERSONAL ARTIFICIAL INTELLIGENCE SYSTEM — COMPLETE AUTONOMOUS BUILD DIRECTIVE
2. SPARKLE GEN-2 — BUILD A NEW PERSONAL AI OPERATING AGENT ON TOP OF THE EXISTING SPARKLE

This audit maps every supplied master section to implementation, execution, persistence, interface and test evidence. COMPLETE records the implemented software boundary described in that row. Test doubles establish software behavior and are never counted as current provider, account, deployment or physical-device acceptance. Whole-system sign-off remains BLOCKED where those external prerequisites or the original documents are missing.

## Fresh validation

- Full authoritative command: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -ra -W error.
- Final software result: 696 passed, 0 failed, 0 skipped; 292 subtests passed (45.55 seconds). Architecture, unit, integration, lifecycle, policy, restart and cross-domain tests are included. New regression cases also cover malformed model constraints, non-list plan steps and exception-supplied diagnostic fields.
- Python compileall, 11 JavaScript syntax checks, pip check and Git whitespace checks pass. No standalone lint/type-check configuration or frontend build pipeline is configured.
- A newly built wheel contains all 13 required web assets, with zero missing. Installation, all three CLI entry-point helps and Personal Core startup from the installed prefix outside the checkout pass.
- Fresh installed HTTP smoke: root, app.js, app.css and workspace module return 200; unauthenticated execution API returns 401. Authenticated route/owner/scope contracts are in the full suite.
- Browser acceptance uses an isolated enrolled test device and real HTTP/API/UI state. All 14 main views load; project create/edit persist; captured-task inspection works; desktop and 412×915 mobile navigation/reload pass, with no horizontal overflow or JavaScript errors.
- A production natural-language request, “I want to calculate 2+2 and then calculate 3+3.”, uses the actual native hosted provider and Gen-1 calculator. The first invalid proposal is rejected; safe validation feedback permits a corrected second plan. Both steps are independently VERIFIED, results are 4 and 6, all three criteria are SATISFIED, and the goal/run persist as COMPLETED. Planning calls: 2; tool iterations: 2; active runtime: 211.27 seconds. Default fallback stays false. The initial browser harness wait was shorter than the provider response; completion was confirmed afterward by persisted reread and the final UI.
- Verification uses separate temporary databases/native data and deliberately disables external connector activation for that test server. This does not establish absence of credentials in the user's production configuration. The production user service was observed inactive and was not started, restarted or deployed.

## Limits and trust boundaries

Arbitrary synchronous native calls are not forcibly terminated. Runtime/step limits are checked around calls, a late response is recorded as a timeout, and state-changing work is not automatically replayed. Adapters own transport deadlines. Planning/tool/iteration budgets accumulate across runs and replans; measured token usage is retained only when actually reported. Unknown usage/cost/location is not invented and cannot satisfy an explicit bound. Custom/semantic verifiers require an explicitly registered handler.

Personal Core remains a private single-workspace service with scoped devices. Gen-2 owner isolation applies to its views/records/links; inherited native stores/shared sessions are not a new multi-tenant account service. Finishing one bounded execution does not complete an entire project or overwrite its original goal relationship.

Existing Cycle/September provider, account, portal, voice, Android and isolation records retain their original dates and scopes. The packaged acceptance matrix labels them recorded acceptance rather than a current runtime probe. Newly successful calculator planning is the fresh hosted-provider evidence for this pass. No fresh hardware voice, physical IoT/robot/mobile, production deployment or external publishing acceptance is claimed.

## Evidence profiles

Source paths below are relative to src/sparkle_gen2 unless they name repository documentation, tests or pyproject.toml. Test filenames resolve under tests/. Gen-1 implementation is reused through public interfaces and remains unmodified. Profile links in the requirement matrix resolve to these exact source/test groups.

### E1

Durable bounded execution and recovery.

- Files: agents/personal.py; application/execution/{lifecycle_service,approval_service,run_controls,budgets,tool_dispatch,verification}.py; domain/models.py; infrastructure/persistence/store.py.
- Execution: Conversation → PersonalAgent → lifecycle → dispatcher → verifier.
- Persistence: SQLite goals/plans/TaskRun/leases/controls/events.
- Interface: Conversation, Execution, Approvals.
- Tests: test_execution_completion.py; test_cycle2_acceptance.py; test_cycle18_failure_budget_expiry.py; test_gen1_approval_reconciliation.py; test_plan_validation.py.

### E2

Typed capability, tool and specialist contracts.

- Files: domain/contracts/{ports,tool_protocol}.py; application/system/tool_system.py; agent_registry.py; agents/{base,router}.py; gen1.py.
- Execution: Catalog/schema → validated plan → authorized dispatch/delegation.
- Persistence: Correlated steps, results, observations and traces.
- Interface: Conversation, Execution, System.
- Tests: test_tool_protocol_completion.py; test_agent_registry.py; test_cycle46_specialist_delegation.py; test_cycle47_approval_aware_delegation.py; test_gen1_schema_contracts.py.

### E3

Provider-agnostic routing and minimized context.

- Files: infrastructure/providers/{model_manager,model_selection}.py; gen1.py; application/{planner,context_engine,context_sources,retrieval}.py.
- Execution: Request constraints → capability manager → adapter → strict proposal.
- Persistence: Model provenance, planning attempts and measured usage.
- Interface: Conversation, System.
- Tests: test_model_selection_completion.py; test_cycle51_multimodel_architecture.py; test_cycle74_planner_schema_guard.py; test_cycle75_live_planner_criteria.py; test_cycle76_routing_guard.py; test_cycle27_context_integration_device_robot.py.

### E4

Connected owner-scoped Personal OS.

- Files: application/personal_os/{graph,inspector,service,workflows}.py; application/system/personal_core.py; interfaces/http_server.py; web/ui/modules/{os,os-editor,workspace}.js.
- Execution: Saved record → normal goal execution → verified result → source/graph update.
- Persistence: OS records, owner-bound nodes/edges, stable event references.
- Interface: Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity.
- Tests: test_personal_os_completion.py; test_os_graph_and_editing.py; test_cycle38_personal_core_devices.py; test_cycle56_personal_operations_surface.py; test_web_ui_contract.py.

### E5

Evidence-linked knowledge, documents and reviewed memory.

- Files: application/{memory_orchestration,learning_orchestration}.py; application/knowledge/{document_intelligence,personal_data}.py; application/personal_os/graph.py.
- Execution: Ingest/review/assess → independent reread → persisted evidence → graph.
- Persistence: Document chunks, assessments, candidates and approved native memory.
- Interface: Knowledge, Memory, Learning, Skills, Research.
- Tests: test_cycle45_completion_memory.py; test_cycle53_document_intelligence.py; test_gen1_approval_reconciliation.py; test_master_learning_orchestration.py; test_personal_os_completion.py.

### E6

Existing native domain workflows through typed delegation.

- Files: gen1.py; agent_registry.py; agents/router.py; application/planning/delegation.py; application/learning_orchestration.py; application/research_pipeline.py.
- Execution: PersonalAgent → constrained specialist → public Gen-1 service/tool → verification.
- Persistence: Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links.
- Interface: Conversation and linked Personal OS views.
- Tests: test_gen1_boundary.py; test_gen1_schema_contracts.py; test_cycle46_specialist_delegation.py; test_cycle47_approval_aware_delegation.py; test_master_learning_orchestration.py; test_cycle25_research_engineering_loops.py.

### E7

Controlled engineering, builders and artifact workflows.

- Files: gen1.py; application/system/workspace_isolation.py; application/planning/delegation.py; application/system/{rollback,self_improvement}.py; artifacts.py; engineering.py.
- Execution: Inspect → approved scaffold/verify/test/package → artifact reread.
- Persistence: Native workspaces/artifacts/blueprints and durable execution evidence.
- Interface: Conversation, Projects, Execution, Approvals.
- Tests: test_cycle16_engineering_agent.py; test_cycle48_workspace_scaffold_delegation.py; test_cycle49_workspace_verify_delegation.py; test_cycle50_workspace_package_delegation.py; test_cycle77_engineering_binding.py; test_workspace_test_isolation.py; test_workspace_test_isolation_boundary.py.

### E8

Bounded background, proactive, automation and notifications.

- Files: application/background/background.py; application/automation_orchestration.py; application/world/{proactive,daily_os}.py; application/notifications/{notifications,notification_delivery}.py.
- Execution: Event/schedule → relevance/context → policy → bounded task → verified notification.
- Persistence: Definitions, claims, controls, task state, briefs and delivery attempts.
- Interface: Automation, Activity, Approvals, Home.
- Tests: test_cycle19_proactive_pipeline.py; test_cycle52_automation_orchestration.py; test_cycle55_daily_operating_system.py; test_cycle57_notification_intelligence.py; test_cycle60_notification_delivery.py; test_cycle40_background_personal_core.py.

### E9

Permission-bound digital connector/control boundaries.

- Files: infrastructure/connectors/manager.py and typed connector adapters; infrastructure/devices/{computer_adapter,linux_application}.py; application/interaction/interaction.py; environment.py.
- Execution: Authorize → exact adapter action → independent provider/session reread.
- Persistence: Owner/scope/provenance/invocation history; no credential values.
- Interface: Conversation, Approvals, System.
- Tests: test_cycle63_connector_manager.py; test_cycle64_gmail_read.py; test_cycle65_calendar_read.py; test_cycle66_drive_read.py; test_cycle67_github_read.py; test_cycle68_browser_orchestration.py; test_cycle69_linux_application_control.py; test_cycle70_computer_gui_control.py.

### E10

Freshness-aware world, perception and physical safety boundaries.

- Files: application/world/world_model.py; application/robotics/{robotics,perception}.py; infrastructure/devices/{devices,iot_adapter,mqtt_adapter,ros2_adapter,ros2_live,ros2_safety_node}.py; cross_domain.py.
- Execution: Observe/fuse → deterministic safety authorization → bounded action → fresh reread.
- Persistence: World observations, provenance, conflicts, experiments and device state.
- Interface: Conversation, Projects, Knowledge, System, Approvals.
- Tests: test_cycle15_world_cross_domain.py; test_cycle31_semantic_world_iot.py; test_cycle33_mqtt_ros2_contracts.py; test_cycle54_robotics_perception.py; test_master_finalization.py; test_master_finalization_gaps.py; test_master_completion_closure.py.

### E11

Common multimodal and semantic provider boundaries.

- Files: application/voice/voice_runtime.py; infrastructure/providers/{voice_providers,nvidia_models}.py; infrastructure/providers/voice/*_voicechat_transport.py; application/knowledge/multimodal.py; semantic_index.py; model_manager.py.
- Execution: Envelope → classification/capability routing → real adapter or fail-closed → provenance.
- Persistence: Session/goal linkage, document/index/artifact metadata; transient raw audio/image.
- Interface: Conversation, Knowledge, System.
- Tests: test_cycle58_verified_nemotron_providers.py; test_cycle59_rerank_safety_integration.py; test_cycle62_image_generation_integration.py; test_cycle73_gemini_live_voice.py; test_master_multimodal_personal_core.py; test_voicechat_hosted_transport.py.

### E12

Deterministic policy, diagnostics, traces and controlled improvement.

- Files: policy.py; permissions.py; application/system/{audit,diagnostics,observability,failures,self_improvement,rollback}.py; infrastructure/security/protected_secrets.py; application/world/dashboard.py.
- Execution: Deterministic authorization → correlated evidence → diagnosis → approval-gated repair.
- Persistence: Grants, approvals, audit chain, diagnostics, traces and repair records.
- Interface: Approvals, Activity, System, Execution.
- Tests: test_security_acceptance.py; test_cycle2_policy.py; test_cycle21_self_diagnosis.py; test_cycle22_policy_persistence.py; test_cycle26_persistent_improvement_mobile.py; test_master_finalization_gaps.py; test_architecture_boundaries.py.

### E13

Repository, packaging, documentation and release validation.

- Files: ARCHITECTURE.md; docs/{EXECUTION_ENGINE,PERSONAL_GRAPH,MODELS,AGENT_MODEL,TOOLS,MEMORY,PERSONAL_CORE_UI,ACCEPTANCE,TESTING}.md; pyproject.toml; runtime.py; interfaces/{cli,http_server}.py; web/ui/app.js; web/service-worker.js.
- Execution: Approved checkout → source checks → wheel → installed startup → audit → normal Git push.
- Persistence: Git checkpoints/commits plus recorded acceptance provenance.
- Interface: Packaged desktop/mobile Personal Core.
- Tests: Complete warnings-as-errors pytest suite; compileall; Node syntax; pip check; wheel/entry-point/startup/API/browser verification.

## Requirement matrix

| Requirement | Current implementation | Files | Execution path | Persistence | UI | Tests | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Project | Existing Gen-2 repository and compatibility paths evolved | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 2. Authoritative specifications | BLOCKED: both named original documents are absent from the supplied materials | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | BLOCKED |
| 3. Protected boundaries | Opaque archive, native source and Android excluded from edits/staging; no deletion | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 4. Inspect before modifying | Baseline audit and full regression identified and repaired seven failures | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 5. Final architecture | Executable persisted spine connects conversation, execution, verification, recovery and graph | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 6. Core execution engine | Goals, plans, steps, runs, inspections and restart-safe controls persist | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 7. Execution loop | Multi-step execution continues without another message, within policy and budgets | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 8. Verification | Independent returned/state/file/database/HTTP/test/artifact verification; registered semantic/custom verifiers fail closed when absent | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 9. Recovery | Classified bounded retry/replan and explicitly permitted fallback; interrupted writes block replay | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 10. Resources and autonomy | Cumulative iterations/runtime/planning/resource budgets; pause, cancel, leases and restart recovery | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 11. Risk | Deterministic risk decisions cannot be weakened by model output | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 12. Approval | Exact owner/goal/run/step/scope decisions persist and are revalidated after restart | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 13. Capabilities | Catalog exposes actual available handlers and schemas to the planner | [E2](#e2) | Catalog/schema → validated plan → authorized dispatch/delegation | Correlated steps, results, observations and traces | Conversation, Execution, System | [E2](#e2) | COMPLETE |
| 14. Typed tools | Universal definition/input/output/error and permission/risk/verification contracts with bounded validation | [E2](#e2) | Catalog/schema → validated plan → authorized dispatch/delegation | Correlated steps, results, observations and traces | Conversation, Execution, System | [E2](#e2) | COMPLETE |
| 15. Agent protocol | Typed AgentResult and policy-aware specialist delegation | [E2](#e2) | Catalog/schema → validated plan → authorized dispatch/delegation | Correlated steps, results, observations and traces | Conversation, Execution, System | [E2](#e2) | COMPLETE |
| 16. Agents | All 16 named native specialists are bound through shared infrastructure; selected profile persists | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 17. Agent Builder | Real native definitions/configuration, validation and generated-agent workflow; deployment requires a selected authorized target | [E7](#e7) | Inspect → approved scaffold/verify/test/package → artifact reread | Native workspaces/artifacts/blueprints and durable execution evidence | Conversation, Projects, Execution, Approvals | [E7](#e7) | BLOCKED |
| 18. AI System Builder | Real native specifications/plans/compiled drafts/controlled builds; production deployment destination is unspecified | [E7](#e7) | Inspect → approved scaffold/verify/test/package → artifact reread | Native workspaces/artifacts/blueprints and durable execution evidence | Conversation, Projects, Execution, Approvals | [E7](#e7) | BLOCKED |
| 19. Application Builder | Native builder coordinates structured project/workspace artifacts and tests; external deployment destination is unspecified | [E7](#e7) | Inspect → approved scaffold/verify/test/package → artifact reread | Native workspaces/artifacts/blueprints and durable execution evidence | Conversation, Projects, Execution, Approvals | [E7](#e7) | BLOCKED |
| 20. Models | Capability, complexity, latency, configured cost, location, privacy and availability selection; no hidden fallback | [E3](#e3) | Request constraints → capability manager → adapter → strict proposal | Model provenance, planning attempts and measured usage | Conversation, System | [E3](#e3) | COMPLETE |
| 21. Context | Bounded request-relevant owner/source context, with secret exclusion and honest unavailable-source state | [E3](#e3) | Request constraints → capability manager → adapter → strict proposal | Model provenance, planning attempts and measured usage | Conversation, System | [E3](#e3) | COMPLETE |
| 22. Memory | Approval-gated proposal/review/reconciliation; persisted memory alone yields knowledge/decision nodes | [E5](#e5) | Ingest/review/assess → independent reread → persisted evidence → graph | Document chunks, assessments, candidates and approved native memory | Knowledge, Memory, Learning, Skills, Research | [E5](#e5) | COMPLETE |
| 23. Personal knowledge graph | Persistent owner-scoped entities and relationships, including stable event IDs without event payloads | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | COMPLETE |
| 24. World model | Observed/inferred/predicted state, freshness, provenance and contradiction resolution persist | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | COMPLETE |
| 25. Personal OS | Manual records and learning/research/skill/project sources start ordinary authorized execution and retain progress links | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | COMPLETE |
| 26. Learning | Native curricula, timed/manual assessments, progress and skill links; Gen-2 adaptive evidence/weakness/retraining orchestration | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 27. Skills | Evidence-backed native mastery plus linked assessments/projects/learning and restart persistence | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 28. Exams | Native Exam specialist uses the real curriculum/question/answer/deadline/grading engine and skill links | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 29. Research | Native questions/claims/evidence/transition/report plus bounded source/provenance and experiment pipeline | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 30. Data analysis | Native persisted ingestion and bounded recipes/statistics/group/chart outputs, with approved workspace execution for analysis code | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | COMPLETE |
| 31. Projects | Real native/Gen-2 project records, tasks and execution progress; deployment stage requires a selected authorized destination | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | BLOCKED |
| 32. Software engineering | Bound Gen-2 repository inspection and controlled scaffold/verify/test/package workflow with independent evidence | [E7](#e7) | Inspect → approved scaffold/verify/test/package → artifact reread | Native workspaces/artifacts/blueprints and durable execution evidence | Conversation, Projects, Execution, Approvals | [E7](#e7) | COMPLETE |
| 33. Content | Real persisted native content workflow/templates/render/export; publishing and platform analytics require an account/destination | [E6](#e6) | PersonalAgent → constrained specialist → public Gen-1 service/tool → verification | Native learning/skills/research/projects/data/content/blueprints plus Gen-2 links | Conversation and linked Personal OS views | [E6](#e6) | BLOCKED |
| 34. Voice | Shared session/goal/core and provider software contracts pass; fresh microphone/speaker acceptance requires authorized physical capture/output | [E11](#e11) | Envelope → classification/capability routing → real adapter or fail-closed → provenance | Session/goal linkage, document/index/artifact metadata; transient raw audio/image | Conversation, Knowledge, System | [E11](#e11) | BLOCKED |
| 35. Browser and computer | Bounded browser/Linux/control contracts pass; fresh GUI portal control requires an explicitly authorized live portal session | [E9](#e9) | Authorize → exact adapter action → independent provider/session reread | Owner/scope/provenance/invocation history; no credential values | Conversation, Approvals, System | [E9](#e9) | BLOCKED |
| 36. Connectors | Typed adapters and scope/reread/failure contracts; Outlook live acceptance lacks Microsoft OAuth/account | [E9](#e9) | Authorize → exact adapter action → independent provider/session reread | Owner/scope/provenance/invocation history; no credential values | Conversation, Approvals, System | [E9](#e9) | BLOCKED |
| 37. Proactive intelligence | Relevance, context, deterministic policy, deduplication and bounded execution pipeline | [E8](#e8) | Event/schedule → relevance/context → policy → bounded task → verified notification | Definitions, claims, controls, task state, briefs and delivery attempts | Automation, Activity, Approvals, Home | [E8](#e8) | COMPLETE |
| 38. Automation | Exact approved definitions, triggers, claims, controls, cooldown and persisted execution | [E8](#e8) | Event/schedule → relevance/context → policy → bounded task → verified notification | Definitions, claims, controls, task state, briefs and delivery attempts | Automation, Activity, Approvals, Home | [E8](#e8) | COMPLETE |
| 39. Notifications | Owner-bound relevance/delivery/acknowledgement state; unavailable channels are reported honestly | [E8](#e8) | Event/schedule → relevance/context → policy → bounded task → verified notification | Definitions, claims, controls, task state, briefs and delivery attempts | Automation, Activity, Approvals, Home | [E8](#e8) | COMPLETE |
| 40. Trace and observability | Correlated goal/run/step/tool/model/agent events persist; private reasoning and credentials excluded | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 41. Monitoring | Actual diagnostic/capability/connector/device/world/worker projections | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 42. Diagnosis | Evidence-backed failure categories and bounded repair recommendations; no invented cause | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 43. Controlled improvement | Test/review/security/approval/install/record gates and restart-safe rollback | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 44. Experiments | Persisted hypothesis/configuration/method/results/evidence/conclusion and research links | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | COMPLETE |
| 45. Artifacts | Persistent native artifact references and verified metadata linked to execution/project sources | [E7](#e7) | Inspect → approved scaffold/verify/test/package → artifact reread | Native workspaces/artifacts/blueprints and durable execution evidence | Conversation, Projects, Execution, Approvals | [E7](#e7) | COMPLETE |
| 46. Multimodal | Typed common envelopes and provider boundaries; unsupported/unsafe media fail closed | [E11](#e11) | Envelope → classification/capability routing → real adapter or fail-closed → provenance | Session/goal linkage, document/index/artifact metadata; transient raw audio/image | Conversation, Knowledge, System | [E11](#e11) | COMPLETE |
| 47. Embeddings and reranking | Provider-routed chunks/vectors/index/retrieval/reranking/context with privacy and provenance | [E11](#e11) | Envelope → classification/capability routing → real adapter or fail-closed → provenance | Session/goal linkage, document/index/artifact metadata; transient raw audio/image | Conversation, Knowledge, System | [E11](#e11) | COMPLETE |
| 48. Document intelligence | Bounded ingestion, structural parsing, chunks, provenance, indexing/retrieval and owner enforcement | [E5](#e5) | Ingest/review/assess → independent reread → persisted evidence → graph | Document chunks, assessments, candidates and approved native memory | Knowledge, Memory, Learning, Skills, Research | [E5](#e5) | COMPLETE |
| 49. Image generation | Capability-routed generation/result/artifact metadata and integrity/failure contracts | [E11](#e11) | Envelope → classification/capability routing → real adapter or fail-closed → provenance | Session/goal linkage, document/index/artifact metadata; transient raw audio/image | Conversation, Knowledge, System | [E11](#e11) | COMPLETE |
| 50. Devices and IoT | Typed transport, capability and safety software passes; real ESP32/MQTT/mobile targets and credentials are not supplied | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | BLOCKED |
| 51. ROS2 | Allowlisted commands, safety-controller/e-stop/fresh-state contracts pass; a real robot and independent safety setup are absent | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | BLOCKED |
| 52. Perception | Typed identity/fusion/freshness/conflict/provenance pipeline and motion gating | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | COMPLETE |
| 53. Robotics Engineer | Structured engineering profile connects existing learning/skills/projects/research/coding/experiments; motion remains safety-gated | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | COMPLETE |
| 54. Cross-domain completion | Required domains must each produce verified evidence before aggregate completion | [E10](#e10) | Observe/fuse → deterministic safety authorization → bounded action → fresh reread | World observations, provenance, conflicts, experiments and device state | Conversation, Projects, Knowledge, System, Approvals | [E10](#e10) | COMPLETE |
| 55. Natural behavior | Intent recognition routes ordinary goals into durable execution and reports saved progress/errors | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 56. Conversation | Shared persisted sessions, goal/profile links, approvals, continuation and natural responses | [E1](#e1) | Conversation → PersonalAgent → lifecycle → dispatcher → verifier | SQLite goals/plans/TaskRun/leases/controls/events | Conversation, Execution, Approvals | [E1](#e1) | COMPLETE |
| 57. Web interface | Authoritative views, manual editors, loading/empty/error states, inspection/control dialogs and mobile navigation | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | COMPLETE |
| 58. Performance | Bounded context, lazy provider paths, background workers and static module caching; hosted provider latency remains measurable | [E3](#e3) | Request constraints → capability manager → adapter → strict proposal | Model provenance, planning attempts and measured usage | Conversation, System | [E3](#e3) | COMPLETE |
| 59. Security | Central deterministic authorization, owner/scope isolation, bounded schema/paths and protected credential resolution | [E12](#e12) | Deterministic authorization → correlated evidence → diagnosis → approval-gated repair | Grants, approvals, audit chain, diagnostics, traces and repair records | Approvals, Activity, System, Execution | [E12](#e12) | COMPLETE |
| 60. Classification | Classification/privacy filters block unsafe disclosure; safe planning diagnostics omit private payloads | [E3](#e3) | Request constraints → capability manager → adapter → strict proposal | Model provenance, planning attempts and measured usage | Conversation, System | [E3](#e3) | COMPLETE |
| 61. Tests | All 16 required software workflow families mapped below; real-provider evidence is separate | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 62. Regression | Full suite passes after final event projection; assertions strengthened for restart/privacy and corrected intentional cache-version changes | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 63. Acceptance | Connected software flow proven; whole-spec acceptance awaits the original documents and gated external scenarios | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | BLOCKED |
| 64. No fake completion | Fresh versus recorded versus deterministic test evidence explicitly distinguished | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 65. Implementation strategy | Existing layers/services evolved; native foundation reused through interfaces | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 66. Compatibility | Compatibility facades remain; additive persisted fields and public APIs retained | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 67. Documentation | Architecture, execution, graph, models, agents, memory, tools, Personal OS and acceptance/testing updated | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 68. Build order | All 18 phases audited and connected at software boundaries; external acceptance gates remain explicit | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 69. Continuous execution | Work continued across fixes, regression failures and recovered remote transport without unnecessary approval prompts | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 70. Progress updates | Actual findings, checks and blockers reported throughout | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 71. Git checkpoints and push | Checkpoint and meaningful commits; authorized normal push independently verified on GitHub main at implementation commit ee0e16a352d891b1d9605b30905cac1413900599 | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 72. Audit both original specifications | BLOCKED: neither original specification is available; this matrix covers the attached 75-section master directive | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | BLOCKED |
| 73. Final validation | All configured software checks, installed startup, APIs, UI and lifecycle/policy/cross-domain coverage pass | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 74. Final report | Evidence, test counts, limitations, Git publication and protected boundaries recorded for final handoff | [E13](#e13) | Approved checkout → source checks → wheel → installed startup → audit → normal Git push | Git checkpoints/commits plus recorded acceptance provenance | Packaged desktop/mobile Personal Core | [E13](#e13) | COMPLETE |
| 75. Actual connected system | Real connected execution exists; full original-spec and physical/account/deployment sign-off remains gated | [E4](#e4) | Saved record → normal goal execution → verified result → source/graph update | OS records, owner-bound nodes/edges, stable event references | Tasks, Goals, Projects, Learning, Skills, Research, Knowledge, Memory, Execution, Approvals, Automation, Activity | [E4](#e4) | BLOCKED |

## Critical workflow evidence

The following are software end-to-end/integration acceptance families. Native/provider calls are identified above; injected deterministic transports remain test-only.

| Required test | Workflow | Evidence |
| --- | --- | --- |
| 1 | Conversation → goal → plan → native tool → verification → memory/reply | test_vertical_slice.py; test_execution_completion.py; test_gen1_approval_reconciliation.py; test_cycle45_completion_memory.py |
| 2 | Multi-step execution | test_execution_completion.py; test_cycle2_acceptance.py; fresh production browser calculator flow |
| 3 | Failure and retry | test_execution_completion.py; test_cycle18_failure_budget_expiry.py |
| 4 | Failure and explicitly permitted fallback | test_model_selection_completion.py; test_cycle51_multimodel_architecture.py; production default remains fallback=false |
| 5 | Approval-required action | test_cycle2_acceptance.py; test_gen1_approval_reconciliation.py; test_cycle47_approval_aware_delegation.py |
| 6 | Pause and resume | test_execution_completion.py; test_personal_os_completion.py |
| 7 | Process restart and TaskRun recovery | test_execution_completion.py; test_cycle13_worker.py; test_cycle2_acceptance.py |
| 8 | Goal → project → task → execution → result | test_personal_os_completion.py; test_os_graph_and_editing.py |
| 9 | Learning → skill evidence | test_master_learning_orchestration.py; test_personal_os_completion.py; test_gen1_schema_contracts.py |
| 10 | Research → evidence → knowledge | test_master_finalization.py; test_master_finalization_gaps.py; test_personal_os_completion.py |
| 11 | Proactive automation | test_cycle19_proactive_pipeline.py; test_cycle52_automation_orchestration.py |
| 12 | Voice/text shared context | test_cycle29_voice_lifecycle.py; test_cycle73_gemini_live_voice.py |
| 13 | Connector failure | test_cycle63_connector_manager.py; typed Gmail/Calendar/Drive/GitHub failure suites |
| 14 | Permission denial | test_security_acceptance.py; test_cycle2_policy.py; test_cycle47_approval_aware_delegation.py |
| 15 | Critical risk denial | test_security_acceptance.py; test_cycle2_policy.py; test_master_finalization.py |
| 16 | Cross-domain completion | test_cycle15_world_cross_domain.py; test_master_completion_closure.py |

## External prerequisites

- Original specification documents: required to complete the audit against both originals.
- Deployment/publishing: a selected destination, account and exact authority are needed for generated agents, AI systems, applications, project deployment and external content publishing/analytics.
- Voice/GUI: fresh microphone/speaker capture/output and a live authorized desktop portal session are needed for physical voice/GUI acceptance. Software/session/policy boundaries remain covered.
- Outlook: a real Microsoft OAuth/account is needed for fresh live provider acceptance.
- Physical systems: real ESP32/MQTT credentials/targets, an authenticated mobile target, and a ROS2 robot with independent safety-controller/e-stop authorization are needed. Simulated or injected test evidence is not physical acceptance.

## Git publication

Checkpoint: checkpoint/gen2-before-completion-20261006 at 7ffccef82d9014b48c9f8981a2dc40666040f6e6. Implementation milestones: 3372aee, b9a136e and ee0e16a352d891b1d9605b30905cac1413900599. On 2026-10-06 an authorized normal push published the implementation to pexxoraa/SPARKLE-GEN2 main. Git ls-remote and the authenticated GitHub main commit fetch independently confirmed this exact SHA. Publication proof refers to that implementation milestone; the dated acceptance/audit update is committed separately. No force push or protected-path staging was used.

## Protected paths

source_code.zip remains opaque, untracked and excluded from staging. It was not opened, extracted, hashed, copied, regenerated or edited. Gen-1 source and mobile-android were not modified. No repository files were deleted. No credential, cookie, token or secret configuration value was printed or committed. Verification scripts, isolated data and browser images are outside the repository and excluded from the release.
