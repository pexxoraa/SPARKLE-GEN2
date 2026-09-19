# Architecture

## Product architecture

SPARKLE Gen-2 is one persistent Personal Core with multiple authenticated presentation/device clients. `sparkle-personal-core` serves the responsive PWA and the private API. `sparkle-background-worker` resumes persistent background tasks. The CLI remains an administration, recovery, and engineering interface over the same underlying services.

The Personal Core owns shared sessions, conversation history, goals, plans, task runs, approvals, notifications, device identities, world state, deterministic retrieval plus optional externally-blocked semantic interfaces, research/experiments, artifacts, and lifecycle evidence. Devices receive only policy-appropriate scoped state rather than copies of the complete private database.

## Dependency boundary

`PersonalAgent` depends on the `Gen1Gateway` protocol. `LocalGen1Gateway` consumes Gen-1 `SparkleSystem.context`, provider-neutral model routing, and ToolRegistry. `EnvironmentGateway` may add explicitly configured, typed Gen-2 environment capabilities while delegating every Gen-1 capability unchanged. Gen-2 does not copy provider secrets, Gen-1 stores, or worker authentication.

## Trusted execution pipeline

1. Persist a Goal and retrieve bounded relevant context.
2. A provider-neutral planner proposes a strict plan and arguments using only advertised typed capability schemas.
3. Persist model/provider provenance.
4. `PlanValidator` checks schema, capabilities, dependencies, criteria, bounds, and unresolved questions.
5. `PolicyEngine` deterministically produces persistent Permission and RiskEvaluation objects.
6. Approval-required actions stop before execution until a human decision is persisted.
7. Execute through the exact Gen-1 or configured Gen-2 environment capability boundary.
8. Observe the result and independently verify it; provider/model completion claims are not evidence.
9. Evaluate persisted goal criteria deterministically.
10. Mark completion only when every executable step is VERIFIED and every criterion is SATISFIED.
11. Persist bounded operation-trace spans correlated by `TaskRun.trace_id` so planning, action, observation, verification, recovery and completion can be reconstructed after restart.

## Model authority boundary

Models may propose plans and candidate arguments. Models cannot add capabilities, grant or revoke permissions, approve actions, downgrade risk, bypass device scopes, invoke raw motor/GPIO/shell interfaces, self-verify effects, or set final completion state.

## Device and network boundary

Device enrollment uses one-time expiring codes and hashed random credentials. Browser credentials use HttpOnly SameSite cookies; device agents may use bearer credentials. Revocation invalidates all tokens for a device. The Personal Core defaults to loopback and requires TLS for non-loopback binding. Public deployment remains deferred.

See `PERSONAL_CORE_UI.md`, `SECURITY.md`, `INTERACTIONS.md`, `MOBILE.md`, and `ROBOTICS.md` for boundary-specific details.

## Model Manager and capability routing

Gen-2 uses a typed `ModelCapabilityManager` plus `CapabilityRouter` over the existing model-registry conventions. Callers request semantic capabilities such as `planning`, `reasoning`, `coding`, `tool_use`, `multimodal`, `voice`, `embedding`, `reranking`, `image_generation`, or `safety`, together with required input/output modalities. Records remain explicit about provider/model identity, enabled/configured state, capabilities, modalities, tool support, context/output limits when present, latency class, fallback eligibility, and health/provenance. Routing filters unavailable or blocked records and fails closed when no record satisfies the complete requirement set.

The architecture supports multiple records and separate future model slots without changing `PersonalAgent`. Multimodal routing requires an image/document-capable record; voice requires audio input/output; embedding, reranking, image generation, and safety are distinct semantic capabilities and are not silently substituted with ordinary text reasoning. A registered but unreachable model is not considered live: Gen-2 distinguishes `CONFIGURED`, `AVAILABLE`, `HEALTHY`, `UNAVAILABLE`, and `BLOCKED` operational states.

Planner model provenance persists provider, model, selected capability, requested capability set, routing reason, observed health, and fallback state. Gen-1 specialist traces retain their own model-routing decisions. Prompts, hidden reasoning, credentials, and unnecessary raw model inputs are not added to Gen-2 provenance records.

### Current production policy

`src/sparkle_gen2/nemotron_models.json` still contains one enabled NVIDIA Nemotron reasoning/planning/coding/tool-use record and `allow_fallback=false`. No second provider or fallback is activated by this architecture work. Multimodal, embedding, reranking, and safety have certified NVIDIA routes; image generation now has a configured FLUX.2 Klein route; VoiceChat remains transport-blocked. Model availability still depends on the relevant secret/transport being present in the executing runtime. Deterministic authorization, risk, approval, and physical safety policy remain authoritative regardless of any safety-model result.

## First-class Gen-2 automation orchestration

`PersonalAgent` exposes approval-gated Gen-2 automation controls while reusing Gen-1 `ReliableAutomationStore` as the authoritative schedule, claim/lease, retry-attempt, run-history, and condition store. Gen-2 persists only an ownership/correlation binding (`automation_id`, user, source goal, trigger class, required model capabilities, risk, status, last linked goal/background task, and verification state); it does not create a second scheduler database.

Supported Gen-2 trigger classes are `scheduled`, `event`, `condition`, and `deadline`. Scheduled triggers map only to Gen-1 `once`, `daily`, or `weekly` definitions. Event/condition/deadline triggers map only to the lower bounded `proactive_alert` / `memory_deadline` condition schema and its allowlisted alert types; arbitrary executable event handlers are not accepted.

When an `agent` automation fires, Gen-1 retains atomic claim/lease, cooldown, idempotency, attempt, and recurrence semantics. The Gen-2 execution adapter starts a normal `PersonalAgent` goal for the stored user/prompt, links it to the existing `BackgroundTaskService`, and requires the background goal to reach verified completion before the automation run is recorded successful. Any action requiring ordinary PersonalAgent approval still stops at that approval boundary. Automation action model requirements are expressed as semantic capabilities and preflighted by the Gen-2 Model Manager/Capability Router; unavailable optional model capabilities fail explicitly rather than falling back to the reasoning model.

State-changing controls (`create`, `pause`, `resume`, `cancel`, `run-now`) use normal PersonalAgent permission/risk/approval handling with exact tool/argument scope. `automation_inspect` remains the lower read-only inspection boundary. Restart recovery follows Gen-1 lease guarantees: persisted definitions survive process restart; expired in-flight claims are marked `recovered` and become eligible again, but an interrupted execution is not falsely described as in-flight resumable.
## Document intelligence

`DocumentIntelligenceService` is the Gen-2 local-first document boundary. It validates bounded private-root sources, hashes content, performs format-specific local extraction, persists a canonical structured record, and exposes provenance-preserving bounded retrieval to `PersonalAgent`. Binary inputs are not duplicated into a second artifact store. See `DOCUMENT_INTELLIGENCE.md`.

## Robotics perception

`PerceptionService` is the typed bridge from simulation/physical sensor adapters into the existing persistent `WorldModel`. It persists normalized observations separately from current world nodes so timestamp/freshness, confidence, source, and observation provenance survive restart. PersonalAgent can call the read-only `perception_observe` capability; fresh normalized evidence may update the robot world node, while stale or conflicting observations are not treated as current. The existing ROS2 gateway and safety controller remain the action boundary.

## Daily Operating System

`DailyOperatingSystemService` turns bounded `PersonalContextAssembler` output into a persistent provenance-bearing daily priority brief. It reuses existing goals/tasks/projects/connectors/world state as sources and does not create duplicate authoritative stores for them. Brief generation is deterministic/idempotent; item disposition changes use normal PersonalAgent approval and exact scope binding. See `DAILY_OS.md`.

## Personal Operations projection

`PersonalOperationsService` is a typed, bounded projection layer rather than an authoritative subsystem. It reconstructs `PersonalOperationsSnapshot` from existing Daily OS, goal/task/approval/background/notification stores plus capability routing, connectors, runtime devices, WorldModel freshness, and diagnostics. PersonalAgent may read the same projection through `operations_snapshot`, so conversational and PWA status use one deterministic source.

## Notification intelligence / attention orchestration

`NotificationIntelligenceService` is the deterministic attention layer over the existing `NotificationCenter`; it does not create a second notification store. Verified/proactive events are normalized into owner-scoped candidates, evaluated for relevance/urgency, deduplicated by semantic condition + verified state, grouped when equivalent events repeat, checked against a persisted attention budget, and then recorded as `DELIVER`, `AGGREGATE`, `SUPPRESS`, or `ESCALATE`. The final notification remains in the authoritative `notifications` table while bounded candidate/decision provenance is stored separately in `notification_decisions`.

Recovery events resolve the previously surfaced condition and emit one bounded recovery notice; a condition that resolves before any delivery is persisted as a suppression decision instead. Restart reconstructs deduplication and budget state from persisted decisions. Notification logic never approves actions or invokes privileged tools.

## Verified NVIDIA capability routes

The production Gen-2 model registry now carries seven NVIDIA records behind the existing capability router: Lightning for ordinary text reasoning/planning/tool use, Omni for image+text multimodal/perception reasoning, Embed 1B for embeddings, Llama Nemotron Rerank VL 1B v2 for neural reranking, and Nemotron 3.5 Content Safety for advisory safety classification. All have fallback disabled. The embedding provider is installed as a Gen-2 adapter factory in the existing Gen-1 `ModelRegistry`, and the existing Personal Context semantic index consumes it; no parallel model/provider framework was introduced.
Reranking is optional in the normal semantic-index pipeline: when configured, bounded embedding candidates pass through the routed reranker before Personal Context; when unavailable, the pre-existing embedding-only path remains valid. An explicit `reranking` capability request still fails closed. Advisory safety is similarly separate from authorization: deterministic permission/risk/privacy/workspace/device/ROS2/e-stop policy executes independently, and a persisted safety advisory may only preserve or tighten the deterministic decision.

## Notification delivery channel orchestration

The certified Notification Intelligence layer remains authoritative for relevance, suppression, deduplication, aggregation, escalation, and attention budgets. A separate read-only delivery-policy boundary consumes persisted `NotificationDecision` records and projects them into typed channel attempts; it never changes the upstream decision. `dashboard`, `desktop`, `voice`, and `mobile` are first-class channel types. Dashboard delivery is the authoritative Personal Operations/PWA surface and is accepted when the persisted notification exists. Desktop delivery is a Personal Core/PWA pull-and-ack path: an authenticated browser must explicitly report the real `Notification.permission` state, pending attempts are scoped to that device, `ServiceWorkerRegistration.showNotification()` completion records channel `ACCEPTED`, and a notification click separately records `ACKNOWLEDGED`. Voice and mobile are represented as `UNAVAILABLE` until separately configured and accepted.

Delivery attempts are persisted with stable decision/channel/device-derived identities, notification identity, status, timestamps, retry lineage, bounded payload, channel reference, acknowledgement state, and provenance. Replaying the same notification decision or restarting Gen-2 reconstructs missing projections without duplicating existing attempts. Expired pending attempts remain explicit and retries stay linked to the same notification/decision. The Personal Operations projection exposes channel availability, waiting/failed deliveries, important unacknowledged deliveries, and recent results.

## Voice interaction boundary

Voice is a semantic model capability (`voice`) with audio/text input and text/audio output, not a reuse of the text reasoning route. `VoiceSessionService` is an interaction layer over the existing conversation/PersonalAgent path: provider transcription becomes normal user text, all existing planning/authorization/approval/verification semantics run unchanged, and only the resulting SPARKLE response is eligible for voice synthesis/output. Raw input/output audio is bounded in memory and is not stored in ordinary durable state; persisted voice records contain session state, timestamps, transcript only when policy permits, provider/model/request references, goal/trace correlation where produced by PersonalAgent, and outcome.

The NVIDIA VoiceChat record includes the verified NVCF function/version metadata and a secret reference but `requires_verified_transport=true` / `transport_verified=false`. This prevents function health or guessed WebSocket URLs from making the capability routable. Streaming sessions are not automatically resumable after Gen-2 restart; recovery marks them unavailable until a fresh provider session is established.

## Image-generation artifact boundary

`image_generate` is an approval-gated PersonalAgent action whose model selection is semantic: `ModelCapabilityManager.generate_image()` requests only `image_generation` with text input and image output. It cannot select the ordinary reasoning, multimodal-understanding, embedding, reranking, or safety models. The NVIDIA adapter implements the externally verified FLUX.2 Klein request contract without unsupported `cfg_scale`/`mode` fields and with `fallback=false`.

Generation state is persisted before provider execution with a stable request identity derived from owner, parent goal/task/step, prompt digest, classification, and generation parameters. A restart/retry therefore does not claim an in-flight request completed. Valid provider bytes are independently parsed as bounded PNG/JPEG, checked against requested dimensions, written into the existing Gen-1 ArtifactManager root/database under a generated-image manifest, reread through the existing Gen-2 artifact-content boundary, and accepted only when local SHA-256/container/dimensions/request provenance all match. Reprocessing the same verified request reuses the immutable verified artifact rather than re-calling the provider.
## Connector Manager

Gen-2 now has one typed `ConnectorManager` over the existing connector catalog and execution boundaries. It does not create provider-specific schedulers, planners, authorization stores, or execution stacks. Deterministic connector descriptors define provider/system identity, typed operations/capabilities, scopes, operation mode (`READ`, `WRITE`, or `CONTROL`), central policy capability, symbolic secret references, authorization mode, optional external dependency, and device scoping.

The common lifecycle is explicit: `DISCOVER → CONNECT → HEALTH → AUTHORIZE → INVOKE → VERIFY → REVOKE`. Durable owner-scoped connection state distinguishes `UNCONFIGURED`, `DISCOVERED`, `CONNECTING`, `CONNECTED`, `AUTH_REQUIRED`, `AUTHORIZED`, `HEALTHY`, `DEGRADED`, `UNAVAILABLE`, `BLOCKED`, `REVOKED`, and `FAILED`. Authorization state is separately represented as `NOT_REQUIRED`, `NOT_CONFIGURED`, `REQUIRED`, `PENDING`, `AUTHORIZED`, `EXPIRED`, `REVOKED`, or `FAILED`; registration/configuration/connection/authorization/health are therefore never treated as synonyms.

Connector invocation carries a stable request identity plus owner, goal, task-run, trace, classification, risk/authorization outcome, approval reference where needed, and an arguments digest. The manager asks the existing `PolicyEngine` for the descriptor's `policy_capability`; `connector_read` is bounded read-only policy, while `connector_write` requires the existing human-approval path. `PersonalAgent` exposes read-only connector list/inspect/capabilities/health tools and one conservatively approval-gated `connector_invoke` tool. Model-supplied approval fields are rejected and never become authority.

State-changing connector calls are not complete merely because an adapter returns. Every adapter must supply an independent `verify()` result; the manager persists `VERIFIED` only when that evidence is true. Read-only adapters similarly preserve source/tool identity and verification evidence. Persisted connector rows contain bounded result summaries and provenance, not raw OAuth tokens, API keys, authorization headers, cookies, or large provider payloads.

The default catalog registers Gmail, Outlook, Calendar, Drive, GitHub, Files, Browser, Linux, IoT, and ROS 2, plus legacy Computer/ESP32/Mobile/MQTT surfaces for compatibility. Registration does not imply activation. External OAuth/device connectors remain `EXTERNALLY_BLOCKED` until an adapter and required authorization/configuration actually exist. The Files connector is the first operational local connector and wraps the existing Gen-1 `file_read` tool through `Gen1ToolConnector`; it does not add a second filesystem implementation. ROS 2 is exposed only when the already-existing environment gateway publishes its safe simulation tools, so connector routing cannot bypass ROS2 safety/e-stop policy.
