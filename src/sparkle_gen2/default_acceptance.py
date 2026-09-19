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
      'knowledge_projects_tasks_learning_research':'real Gen1 read-tool acceptance plus schema contracts',
      'world_model_knowledge_graph':'restart-safe persisted node/edge state with freshness/provenance and bounded relationship queries',
      'advanced_world_model':'freshness-aware typed state and relationship queries survive restart',
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
      'oauth_connector_software':'credential-reference OAuth adapter enforces declared scopes, hides token values, verifies provider operations and revokes connections',
      'browser_control':'real Gen-2 -> Gen-1 safe HTTPS browser session fetched example.com with HTTP 200 and persisted-history verification',
      'gen1_interaction_boundary':'Gen-2 browser/computer adapters use Gen-1 revisioned allowlisted session APIs; no model-tool bypass',
      'digital_control_verification':'observe -> bounded action -> observe -> adapter verification workflow test',
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
      'rollback':'approval + independent rollback verification tests',
    }
    for capability,evidence in verified.items():m.set(CapabilityState(capability,'LIVE_VERIFIED',evidence))
    blocked={
      'image_generation':('NVIDIA credential unavailable in current Gen-2 runtime','NVIDIA FLUX.2 Klein provider was externally verified; routed adapter, approval boundary, immutable artifact persistence, local image/digest reread, idempotency and privacy software are complete; Gen-2 live provider acceptance awaits runtime credential resolution'),
      'voice_stt_tts':('verified NVIDIA VoiceChat NVCF streaming transport + microphone/speaker target','typed VoiceChat session/audio/transcript/provenance boundary and PersonalAgent bridge complete; hosted streaming transport remains unverified'),
      'gmail':('Google OAuth/account','least-privilege connector plus credential-reference OAuth lifecycle software complete'),
      'outlook':('Microsoft OAuth/account','least-privilege connector plus credential-reference OAuth lifecycle software complete'),
      'calendar':('calendar OAuth/account','least-privilege connector plus credential-reference OAuth lifecycle software complete'),
      'drive':('Drive OAuth/account','least-privilege connector plus credential-reference OAuth lifecycle software complete'),
      'github_connector':('GitHub authorization/token','least-privilege connector plus credential-reference OAuth/token lifecycle software complete'),
      'gui_computer_control':('approved GUI/computer-control environment','Gen-1 revisioned allowlisted computer-session adapter plus observe/action/verify software harness complete'),
      'linux_application_control':('approved Linux application-control adapter','bounded allowlisted observe/action/verify control harness complete'),
      'mobile':('mobile target/emulator','complete install/authenticate/execute/persist/reopen/sync/notify/verify/logout software lifecycle; real target unavailable'),
      'esp32':('ESP32 device + authenticated transport','device connector contract complete'),
      'mqtt':('MQTT broker/device credentials','topic-bounded transport, health and independent verification software complete'),
      'ros2_robotics':('ROS2 robot gateway + safety controller + independent e-stop','allowlisted ROS2 transport, safety authorization, direct-motor denial/e-stop and independent post-command verification complete'),
      'robotics_engineer_live':('real robot/ROS2 target','mode software preserves RobotSafetyGateway'),
      'workspace_test_execution':('dedicated disposable worker with SPARKLE_WORKSPACE_TESTS_ENABLED=true','real Gen1 explicitly refuses tests when disabled; scaffold/compile/package verified'),
      'source_control_push':('noninteractive GitHub write authentication on host','repository remote is correct; remote reads work; pushes wait for auth'),
    }
    for capability,(dependency,evidence) in blocked.items():m.set(CapabilityState(capability,'EXTERNALLY_BLOCKED',evidence,dependency))
    m.set(CapabilityState('production_deployment','DEFERRED','No deployment target/runtime was specified; repository and local runtime remain testable',limitation='deployment target selection is a human/environment decision'))
    if runtime_evidence_path is not None:
        from .activation_evidence import load_activation_evidence
        for capability,record in load_activation_evidence(runtime_evidence_path).items():
            if capability not in m.items or record.get('status') not in {'LIVE_VERIFIED','EXTERNALLY_BLOCKED','DEFERRED'}:continue
            details=[record.get('evidence','')]
            for key in ('provider','environment','test_id','timestamp','failure_reason'):
                if record.get(key):details.append(f"{key}={record[key]}")
            dependency=None if record['status']=='LIVE_VERIFIED' else m.items[capability].dependency
            m.set(CapabilityState(capability,record['status'],'; '.join(details),dependency,m.items[capability].limitation))
    return m
