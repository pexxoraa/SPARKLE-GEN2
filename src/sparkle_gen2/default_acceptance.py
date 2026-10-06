from __future__ import annotations
from .capability_status import CapabilityMatrix,CapabilityState

def build_acceptance_matrix(runtime_evidence_path=None):
    m=CapabilityMatrix()
    verified={
      'personal_agent':'Cycle1/2 vertical-slice and goal tests',
      'goal_plan_task_lifecycle':'persistent restart/retry/cancel/deadline/replan tests',
      'plan_validation':'schema/capability/dependency/cycle/policy negative tests',
      'permission_risk_approval':'typed permission/risk restart readback plus Cycle2 policy/security acceptance and persisted approval expiry enforcement',
      'permission_lifecycle':'persistent grant/revoke/expire/authorize service rejects model self-grant/revoke',
      'approval_reconciliation':'Gen2 restart + real Gen1 memory-review approve/reject integration',
      'goal_evaluation':'independent success-criterion tests',
      'session_continuity':'persistent session restart test',
      'personal_context_engine':'integrated PersonalAgent context path selects bounded personal, connector, goal, device, world and recent-activity context',
      'personal_context_source_coverage':'software context assembler covers memory/knowledge/projects/tasks/research/learning/preferences/calendar/email/files/goals/devices/world/recent activity when sources are available',
      'background_task_engine':'persistent start/pause/resume/retry/cancel/recover/inspect lifecycle with iteration and wall-time budgets',
      'background_worker':'bounded worker pass tests',
      'proactive_event_engine':'event -> relevance -> context -> decision -> deterministic policy -> action/notification pipeline tests',
      'memory_orchestration':'real Gen1 memory proposal/review/reconciliation test',
      'knowledge_projects_tasks_learning_research':'real Gen1 read-tool acceptance plus schema contracts; Gen-2 adaptive learning adds approval-gated persistent curricula/assessments, deterministic weakness/mastery thresholds, retraining state, owner isolation and restart recovery',
      'world_model_knowledge_graph':'restart-safe persisted node/edge state with freshness/provenance, bounded relationship queries/upserts, and cross-source contradiction tracking plus explicit provenance-backed resolution',
      'advanced_world_model':'freshness-aware observed/inferred/predicted typed state, conflict metadata, relationship queries and restart persistence',
      'cross_domain_completion':'bounded multi-domain coordinator requires independent verification for every required domain',
      'autonomous_software_engineering_orchestration':'bounded approval-gated scaffold/verify/test/package state machine; stops before package when tests are unavailable',
      'deterministic_security_policy':'risk/approval/shell-denial/self-completion security tests',
      'audit_log':'tamper-evident hash-chain test',
      'model_manager_capability_routing':'Gen1 ModelRouter integration and health/capability filtering tests',
      'live_model_planning':'Cycle58 real PersonalAgent goal used NVIDIA Nemotron 3.5 Lightning planning, calculator execution, independent verification and COMPLETED with fallback=false',
      'semantic_retrieval_pipeline':'Cycle58 real Nemotron Embed 1B vectors feed PersistentSemanticIndex and bounded PersonalContextAssembler semantic evidence',
      'embedding_provider':'Cycle58 real NVIDIA Nemotron Embed 1B call through capability router returned 2048-dimensional embeddings with fallback=false',
      'semantic_multimodal':'Cycle58 real NVIDIA Nemotron Omni image inference through DocumentIntelligenceService persisted grounded image description and model provenance; sensitive classification remained blocked',
      'reranking_provider':'Cycle59 real NVIDIA llama-nemotron-rerank-vl-1b-v2 call through CapabilityRouter reranked bounded semantic candidates and propagated model provenance into Personal Context with fallback=false',
      'safety_model':'Cycle59 real NVIDIA nemotron-3.5-content-safety advisory calls returned safe/unsafe signals, persisted provider/model/request/reference/timestamp provenance, preserved safe deterministic policy and only escalated flagged ALLOW to approval',
      'model_failure_recovery':'planner retry/fail-closed/replan plus explicit execution failure classification',
      'typed_tool_catalog':'CapabilityDescriptor/Catalog tests',
      'independent_write_verification':'real Gen1 memory/workspace/agent state is re-read before durable writes are accepted as verified',
      'connector_manager':'explicit discover/authorize/connect/health/invoke/verify/revoke lifecycle with granted-scope enforcement',
      'gmail':'Cycle64/CycleMaster real Gen-2 Gmail readonly route authenticated through protected OAuth config, returned a bounded real mailbox result and independently reread selected message identity',
      'calendar':'Cycle65/CycleMaster real Gen-2 Google Calendar readonly route authenticated through protected OAuth config, returned bounded calendar data and independently reread selected calendar identity',
      'drive':'Cycle66/CycleMaster real Gen-2 Google Drive readonly route authenticated through protected OAuth config, returned bounded file metadata and independently reread selected file identity',
      'github_connector':'Cycle67/CycleMaster real Gen-2 GitHub readonly route authenticated through protected token config, returned bounded repository metadata and independently reread selected repository identity',
      'image_generation':'CycleMaster resolved the existing protected NVIDIA key through the Gen-2 protected-secret boundary and real FLUX.2 Klein generation returned fulfilled 512x512 JPEG output with provider request ID, fallback=false, and independent SHA-256 reread',
      'oauth_connector_software':'credential-reference OAuth adapter enforces declared scopes, hides token values, verifies provider operations and revokes connections',
      'browser_control':'real Gen-2 -> Gen-1 safe HTTPS browser session fetched example.com with HTTP 200 and persisted-history verification',
      'linux_application_control':'Cycle69 real PersonalAgent -> ConnectorManager -> bounded local Linux adapter inspected OS/disk/memory and executed one approved harmless process with independent postcondition verification and restart-safe provenance',
      'gen1_interaction_boundary':'Gen-2 Browser uses the Gen-1 revisioned allowlisted session API; Computer control is separately constrained by the XDG portal boundary',
      'digital_control_verification':'observe -> bounded action -> observe -> adapter verification workflow test',
      'gui_computer_control':'Cycle70 real GNOME Wayland XDG portal session selected ScreenCast monitor plus keyboard/pointer devices, PersonalAgent observed a live PipeWire frame, approval-gated pointer movement executed through RemoteDesktop, fresh frame verification passed, and restart did not resurrect the session',
      'voice_interruption_control':'turn-level interruption prevents synthesized output handoff after cancellation',
      'voice_turn_lifecycle':'software interrupt/resume/cancel lifecycle tests with active-turn state',
      'shared_voice_text_context':'voice and text turns attach to the same persisted session/goal context',
      'human_readable_progress':'default CLI remains natural; verbose mode renders checked/completed/approval/next summaries without raw reasoning',
      'files_read':'real Gen1 bounded file/engineering inspection boundary',
      'natural_cli':'sparkle/chat alias, optional JSON/verbose, approval/resume/cancel/session tests',
      'dashboard':'typed bounded Personal Operations Surface over persisted Daily Brief/goals/tasks/approvals/background/notifications/capabilities/world/diagnostics with authenticated PWA/API and policy-preserving approval continuation',
      'notifications':'owner-scoped notification intelligence over NotificationCenter with relevance, deduplication, aggregation, suppression, attention budget, escalation, recovery, provenance and explainability',
      'multimodal_transport':'typed transport validation for text/image/audio/document/video/screen/camera',
      'device_manager':'typed connection/capability/permission/safety/firmware/last-seen metadata plus approval-gated independently verified adapter contract',
      'device_safety_contract':'typed device metadata/capabilities preserve policy gate, deny raw GPIO/undeclared actions and require adapter state verification',
      'mqtt_transport_software':'topic-allowlisted MQTT read/publish adapter with broker health and independent verification contract',
      'ros2_gateway_software':'allowlisted ROS2 adapter requires independent safety-controller authorization/e-stop and post-action state verification',
      'experiment_management':'restart-safe evidence-required experiment lifecycle includes configuration/dataset/code/model/results/metrics/project/research links',
      'research_to_experiment':'bounded research comparison -> candidate -> approval -> verified experiment execution -> metrics/analysis/documentation pipeline',
      'artifact_generation':'real isolated Gen1 scaffold + compile verification + package acceptance',
      'image_artifact_provenance':'image-generation software attaches provider/time/goal/project/task provenance without claiming provider live',
      'advanced_coding_foundation':'real Gen1 engineering inspect/scaffold/verify/package plus approval gates',
      'software_engineering_loop':'bounded inspect/implement/test/diagnose/fix/retest/review/report state-machine tests over controlled workflow',
      'daily_operating_system':'persistent owner-scoped DailyBrief lifecycle over bounded Personal Context with provenance, idempotency, approved disposition updates, restart and unresolved carry-forward',
      'controlled_self_improvement':'restart-safe discover/design/implement/test/review/human-approval/install lifecycle with verified registration',
      'notification_persistence':'notification read/unread state survives Gen-2 restart',
      'retrieval_quality_evaluation':'labeled relevance MRR/recall evaluator independently measures deterministic retrieval output',
      'mobile_lifecycle_software':'install/authenticate/execute/persist/reopen/sync/notify/verify/logout lifecycle executes against injected target and fails closed without one',
      'self_diagnostics':'actual Gen1 model/provider/tool/agent, connector, device, storage and background-task inspection with evidence-backed causes',
      'self_monitoring':'diagnostic snapshots expose blocked/failed components without guessing or secret values',
      'observability':'goal/task/trace correlation tests',
      'rollback':'restart-safe generic rollback records require explicit approval, trusted executor, bounded evidence and independent verification; interrupted rollback reconciles to FAILED after restart',
      'workspace_test_execution':'real PersonalAgent workspace_test waited for exact persisted human approval, issued and consumed a one-use owner/goal/task/step/workspace-scoped Gen-2 execution grant, executed through the strict local Bubblewrap profile SPARKLE-GEN2-WORKSPACE-STRICT/1 with a read-only namespace root and only the disposable workspace writable, independently verified filesystem/network/process/environment/credential isolation plus resource limits and hostile canaries, failed closed on live timeout/output attacks while retaining the certified 500-file/5 MB source-bundle ceilings, destroyed the ephemeral worker copy, rejected stale execution handles after restart, and required fresh approval for a new execution',
      'voice_stt_tts':'Gemini 3.8 Live is live accepted through the production VoiceSessionService/PersonalAgent boundary: 24 kHz SPARKLE PCM is converted only at the Gemini boundary to 16 kHz PCM input, real input transcription and BLOCKING function delegation are validated, PersonalAgent executes and independently verifies real tools, approval-sensitive work returns no final provider audio until exact human approval and resume, FunctionResponse then produces real 24 kHz Gemini audio; replay/forged authority/session isolation/raw-audio persistence protections are regression-covered and NVIDIA remains independently registered but blocked',
    }
    for capability,evidence in verified.items():m.set(CapabilityState(capability,'LIVE_VERIFIED',evidence))
    blocked={
      'outlook':('Microsoft OAuth/account','bounded Microsoft Graph read/draft/send adapter, immutable-ID reread verification, central approval policy and credential isolation are implemented; no real Microsoft credential is configured'),
      'mobile':('authenticated physical mobile target or emulator transport','Native Android post-enrollment persistence is software-fixed and build/lint/unit/instrumentation-APK validated: Android Keystore generates the AES-GCM IV, encrypted token + device identity persist atomically and are reread before paired state, post-201 persistence failure clears partial credentials plus the consumed enrollment code, duplicate pairing remains single-flight, auth preferences are excluded from backup/transfer, and cleartext HTTP is restricted to localhost:8787 for ADB reverse. The current host exposes no attached ADB/USB Android target, so on-device install/restart/chat/forget/re-pair acceptance remains external and no live mobile claim is made'),
      'esp32':('ESP32 device + authenticated transport','CycleMaster TypedIoTAdapter provides device/owner binding, declared capability and safety-limit enforcement, raw-GPIO denial and independent transport reread; no physical ESP32 is connected'),
      'mqtt':('MQTT broker/device credentials','topic-bounded transport with wildcard denial, bounded message payloads, authenticated/TLS health assertions when advertised, and independent verification software complete'),
      'ros2_robotics':('ROS2 robot gateway + safety controller + independent e-stop','allowlisted ROS2 transport, safety authorization, direct-motor denial/e-stop and independent post-command verification complete'),
      'robotics_engineer_live':('real robot/ROS2 target','bounded Robotics Engineer workspace now projects existing robot/world/perception/experiment/document state and verified motion remains gated by RobotSafetyGateway; no physical robot/ROS2 target is connected'),
      'source_control_push':('explicit authorization for a real remote write during an acceptance run','repository remote reads work and a noninteractive write dry-run authenticated successfully during master finalization; this run explicitly forbids real pushes, so no remote mutation was performed and live write acceptance remains blocked by run policy'),
    }
    for capability,(dependency,evidence) in blocked.items():m.set(CapabilityState(capability,'EXTERNALLY_BLOCKED',evidence,dependency))
    m.set(CapabilityState('production_deployment','DEFERRED','No deployment target/runtime was specified; repository and local runtime remain testable',limitation='deployment target selection is a human/environment decision'))
    for state in m.items.values():state.evidence_source='recorded_acceptance; not a current runtime probe'
    if runtime_evidence_path is not None:
        from .activation_evidence import load_activation_evidence
        for capability,record in load_activation_evidence(runtime_evidence_path).items():
            if capability not in m.items or record.get('status') not in {'LIVE_VERIFIED','EXTERNALLY_BLOCKED','DEFERRED'}:continue
            details=[record.get('evidence','')]
            for key in ('provider','environment','test_id','timestamp','failure_reason'):
                if record.get(key):details.append(f"{key}={record[key]}")
            dependency=None if record['status']=='LIVE_VERIFIED' else m.items[capability].dependency
            m.set(CapabilityState(capability,record['status'],'; '.join(details),dependency,m.items[capability].limitation,'configured runtime evidence; inspect its timestamp'))
    return m
