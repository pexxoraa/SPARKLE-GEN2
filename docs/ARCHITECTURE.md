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

## Gmail read connector

The central `ConnectorManager` now has a provider-backed Gmail read adapter using the official Google Gmail API client. The registered Gmail surface is intentionally read-only: `list_messages` and `get_message_metadata` share the single internal authorization scope `gmail.read`, which maps to the provider scope `https://www.googleapis.com/auth/gmail.readonly`. Draft, send, delete, modify, and full-body operations are not registered.

OAuth material remains outside the repository behind the symbolic `SPARKLE_GMAIL_TOKEN_FILE` configuration reference. The local `GmailCredentialSource` resolves the established private workstation configuration boundary and loads Google credentials in memory; it does not create a Gen-2 token store. Production entrypoints explicitly activate authorized external connectors, while ordinary library/test composition remains deterministic and does not contact a mailbox unless requested by the test or runtime.

Gmail reads flow through `PersonalAgent → connector_read → ConnectorManager → GmailReadAdapter → Gmail API → adapter verification → ConnectorManager provenance`. `connector_read` is a read-only PersonalAgent tool and cannot invoke connector write/control capabilities. `gmail.read` remains a central `PolicyEngine` `ALLOW / LOW` capability. The adapter always uses `userId="me"`, bounds list results to 25 (default 5), accepts only a bounded optional Gmail query, and retrieves message content only with Gmail `format=metadata` and an allowlisted header set. Full message bodies are not requested.

Verification is a provider reread, not trust in the first API result. A list result rechecks the authorized Gmail profile identity and rereads bounded metadata for the first returned message; metadata reads re-fetch the same message with the same requested header set and compare a canonical digest. Persisted connector provenance keeps the owner/goal/task/trace request identity, provider operation reference, account reference hash, message-id hashes/counts or metadata digest/counts, and verification status. It does not persist mailbox bodies or raw API responses.
## Google Calendar read-only connector

Google Calendar is integrated through the existing ConnectorManager rather than a separate service framework. The production descriptor exposes only `list_calendars`, `list_events`, and `get_event`, all under `calendar.read` / `READ`; no create, update, delete, move, attendee-modification, or invitation operation is registered. The flow is `PersonalAgent → connector_read → ConnectorManager → CalendarReadAdapter → Google Calendar API → independent reread → ConnectorInvocation provenance`.

OAuth material remains outside the repository behind the symbolic `SPARKLE_CALENDAR_TOKEN_FILE` configuration reference. The authorized provider scope is exactly `https://www.googleapis.com/auth/calendar.readonly`. Calendar listing defaults to 10 items and is capped at 25. Event listing defaults to 10, is capped at 25, and always uses a bounded time window (seven days by default, at most 366 days) with `singleEvents=true` and start-time ordering. Returned objects are typed bounded projections rather than raw Google resources. Calendar/event verification re-reads the authorized primary-calendar identity and a selected resource; exact event reads are digest-compared after reread.
## Google Drive read-only connector

Google Drive metadata/discovery is integrated through the existing ConnectorManager. The production descriptor exposes only `list_files` and `get_file_metadata`, both under `drive.read` / `READ`; no create, upload, update, delete, move, rename, permission/sharing, comment, or content-download operation is registered. The execution flow is `PersonalAgent → connector_read → ConnectorManager → DriveReadAdapter → Google Drive API → independent files.get reread → ConnectorInvocation provenance`.

OAuth material remains outside the repository behind the symbolic `SPARKLE_DRIVE_TOKEN_FILE` configuration reference and the authorized provider scope is exactly `https://www.googleapis.com/auth/drive.readonly`. `list_files` defaults to 10 files, is capped at 25, permits only a bounded 512-character Drive query, and requests only `id`, `name`, `mimeType`, `modifiedTime`, and `size`. Exact metadata reads add only `trashed`. File bytes/content are never requested by this connector. Drive account identity is verified through `about.get(user(permissionId))` and persisted only as an opaque hash reference.
## GitHub read-only connector

GitHub is integrated through the existing ConnectorManager as metadata/discovery-only access. The production descriptor exposes `get_user`, `list_repositories`, `get_repository`, `list_repository_contents`, `list_issues`, `list_pull_requests`, and `list_workflows`, all under `github.read` / `READ`. No issue/PR mutation, comments, merges, branch/commit/push, release, workflow dispatch/cancel, webhook, permission, repository-administration, or organization-administration operation is registered.

The credential remains outside the repository behind `SPARKLE_GITHUB_TOKEN_FILE`; a fine-grained PAT is loaded in memory and sent only through the adapter with `Accept: application/vnd.github+json` and GitHub API version `2022-11-28`. Repository, issue, PR, workflow, and contents results are bounded typed projections rather than raw GitHub JSON. Repository contents are metadata-only and never return file bytes/content. Verification re-reads the authenticated user and selected provider resources; root contents verification uses Git tree metadata so source files are not downloaded.
## Browser orchestration

Cycle68 adds a Gen-2 `BrowserOrchestrator` above the already-verified Gen-1 `Gen1BrowserSession`; it does not launch or embed another browser runtime. Production Browser is owner-scoped and exposes only `browser.navigate`, `browser.read`, and CONTROL-classified `browser.interact`. The first navigation creates a revisioned Gen-1 browser session whose allowlist is locked to that HTTPS host. Subsequent navigation/interaction cannot widen the host boundary. Gen-1 remains responsible for DNS/public-IP validation, redirect revalidation, response byte limits, revision conflicts, persistent interaction history, TTL, and session close.

Gen-2 adds conservative orchestration limits: URLs <=2048 characters, visible text <=10,000 characters, <=25 link summaries, timeout <=30 seconds, <=10 CONTROL interactions, and <=20 orchestration history URLs. `browser.interact` supports only `open_link` for an explicitly observed same-host visible URL plus bounded `back`, `forward`, and `reload`; form submission, typing, purchasing, messaging, settings/account changes, downloads, and arbitrary DOM actions are not allowlisted. The protected Gen-1 browser runtime does not expose DOM anchors or screenshots, so Cycle68 does not invent those primitives: links are recognized only when HTTPS URLs are present in the bounded visible text, and screenshot references are typed but runtime capture remains unavailable.
## Linux application control

Cycle69 activates the device-scoped `linux` connector through a Gen-2 `LinuxApplicationAdapter`. It is a structured argv execution boundary, not a free-form command interface. `linux.inspect` is READ and exposes only fixed inspection kinds (`cwd`, `os`, `identity`, `disk`, `memory`, `list_directory`). `linux.execute` is CONTROL and currently exposes one harmless approved action, `launch_sleep_probe`, mapped internally to an allowlisted absolute executable. Callers never supply executable paths or free-form command strings.

The adapter deterministically resolves only a tiny fixed executable set (`pwd`, `uname`, `id`, `df`, `free`, and the CONTROL `sleep` probe), runs with a sanitized `PATH/LANG/LC_ALL` environment, uses argv execution, and caps arguments, command size, timeout, output bytes/lines, directory entries, and CONTROL actions. Production filesystem access is confined to the SPARKLE-GEN2 repository root; traversal, absolute escape, encoded traversal, and symlink-path escape are rejected. ConnectorManager binds Linux to an opaque local device identity derived from the host and rejects any caller-supplied mismatch.
## Computer / GUI control on GNOME Wayland

Cycle70 activates the device-scoped `computer` connector using the existing XDG Desktop Portal services on the local GNOME Wayland session. `ComputerAdapter` launches only a fixed `/usr/bin/python3` helper with a fixed repository helper path and fixed environment; the helper uses system PyGObject/Gio plus the installed GStreamer `pipewiresrc` plugin. No Playwright/Selenium/XTest/raw-input stack is introduced. The helper handles asynchronous `org.freedesktop.portal.Request::Response` objects for RemoteDesktop, ScreenCast and Screenshot rather than treating method-return request handles as authorization results.

The connector retains the existing operations `computer.read` (READ) and `computer.act` (CONTROL). Read actions are `inspect`, `status`, `screenshot`, and `observe`. A live control session is explicitly authorized through RemoteDesktop.CreateSession, ScreenCast.SelectSources, RemoteDesktop.SelectDevices and RemoteDesktop.Start; the requested device mask is pointer+keyboard only and the requested visual source is a single monitor. ScreenCast.OpenPipeWireRemote plus GStreamer provides in-memory RGB frames and verified stream dimensions. Screenshot v2 is the bounded one-shot fallback and its temporary portal file is hashed, dimension-checked, then removed.
## Mobile device connector boundary

Cycle72 reuses the existing device-identity, Personal Core, cross-device session, and notification/sync abstractions rather than creating a mobile-specific trust store. `mobile` remains device-scoped. The production composition accepts an optional trusted `mobile_adapter`; when absent, the connector remains `EXTERNALLY_BLOCKED`. When present, the adapter must already be bound to an authenticated, ONLINE, non-revoked mobile device identity before ConnectorManager can authorize `mobile.read` and `mobile.act`.
## Master-finalization hardening

The finalization pass preserves one architecture per responsibility. Protected Gen-2 configuration now resolves only an explicit allowlist of model secret references and owner-only credential-file references; Gmail, Calendar, Drive and GitHub adapters consume the same already-certified provider implementations. Multimodal transport normalizes caller-supplied bytes only, validates MIME/magic/size, strips source metadata, computes a digest and routes only to registered model modalities. Proactive events have bounded payloads/queues, deterministic replay fingerprints, correlation IDs and priorities. World nodes/edges explicitly distinguish `observed`, `inferred` and `predicted` state with confidence.

Automation now includes an explicit durable `disable` state. Experiments support bounded create/configure/run/pause/resume/cancel/analyze/compare/conclude/archive with resource limits and mandatory independent run verification. Generic robot control adds deterministic velocity, displacement, angle, command-rate, stale-state and optional workspace bounds below the approval layer. Typed IoT/ESP32 integration requires an already-authenticated device transport and denies raw GPIO. Outlook has a bounded Graph adapter but remains inactive without Microsoft authorization.

## Master-finalization state integrity

Generic rollback metadata now uses the existing Gen-2 SQLite store. A rollback record is restart-safe, remains approval-gated, uses a trusted caller-supplied executor, persists only bounded verification evidence, and reconciles an interrupted EXECUTING record to truthful FAILED state after restart rather than silently resuming authority.

The existing WorldModel now also provides bounded contradiction tracking for cross-source state changes, explicit provenance-backed contradiction resolution, idempotent relationship upserts, and bounded graph queries. It retains observed/inferred/predicted epistemic state and confidence rather than converting inference into observation.
## Adaptive learning orchestration

Gen-2 now layers a restart-safe `LearningOrchestrator` over the existing authoritative Gen-1 `learning_progress` surface. A learning plan contains an owner, subject, objective, bounded curriculum units, assessments, weakness state, retraining recommendations, and provenance. Gen-1 progress is consumed only when independently verified; Gen-2 persists a digest/field shape rather than copying arbitrary raw progress payloads. Curriculum creation and assessment recording are state-changing operations and therefore use the existing exact-scope human approval path. Inspection is read-only. Mastery, weakness, and retraining are computed deterministically from approved assessment scores; model prose cannot mark a skill mastered.
