# Security

The model is not the security, permission, execution, device-authentication, or verification boundary.

Deterministic policy remains authoritative. Models cannot self-approve, downgrade risk, add permissions, revoke devices, bypass capability scopes, expose credentials, self-verify, or self-install improvements. State-changing actions retain approval requirements where policy requires them. User autonomy modes are an additional restriction for unattended execution and cannot override `REQUIRE_APPROVAL` or `DENY`.

## Personal Core and devices

Device pairing codes are single-use and expire. Device credentials are random and stored server-side only as hashes. Web credentials are issued in HttpOnly SameSite cookies; native/device-agent credentials use bearer authentication. Every authenticated API request re-checks current device revocation and scope. A revoked device loses all associated tokens.

The Personal Core defaults to `127.0.0.1`. Non-loopback binding requires configured TLS. No public exposure is created automatically. Static PWA assets may be cached; API and personal-state responses are not service-worker cached and API responses use `Cache-Control: no-store`.

## Execution and verification

Gen-1 ToolRegistry remains authoritative for Gen-1 tools with exact allow sets. Gen-2 environment adapters expose only typed, bounded capabilities. ROS2 simulation retains a separate safety controller, e-stop, bounded movement and independent state reread. Raw motor/GPIO paths remain denied.

The isolated workspace worker uses authenticated requests, TLS, fixed operation schemas, explicit identity, resource limits, ephemeral Bubblewrap filesystem/network isolation, hostile canaries, and signed result evidence. Unsafe process execution is not treated as isolated evidence.

Audit and lifecycle state are persisted. Hidden reasoning, raw credentials, and secret values are not exposed through the daily-use UI.

## Workspace test execution boundary

The installed Bubblewrap worker currently passes its hostile isolation canaries for host filesystem read/write, workspace escape, secret environment, prohibited network, host process access, and artifact modification. However, the model-visible Gen-1 `workspace_test` tool is wired to the separate local `WorkspaceTestRunner`, which is disabled by default and explicitly reports no filesystem or network isolation. Gen-2 therefore does not delegate `workspace_test` merely because `bwrap` is present. In the current deployment it remains `SOFTWARE_READY / EXTERNALLY_BLOCKED` until the authenticated isolated worker is configured as the authoritative test-execution boundary. Enabling the local runner or weakening its checks is not an acceptable substitute.

## Automation authority

Automation definitions are not permanent unrestricted grants. Gen-2 binds each automation to an owner, source goal, bounded action prompt/capabilities, risk classification, and the lower trigger definition. Creating or mutating automation state requires the normal PersonalAgent approval boundary. When an automation later launches a goal, that goal re-enters ordinary planning, permissions, approvals, execution, observation, and verification; the automation does not inherit authority to bypass those controls.

## Document security

Document sources must be regular non-symlink files inside an explicitly authorized root, with bounded input size and bounded OOXML member/uncompressed size. Unsupported or malformed content fails closed. Structured records retain classification and digest provenance; full local paths are not persisted in document records. Sensitive classifications are not injected into external-model planning context by default, and image/scanned-document semantics are not faked through the text-only model.

## Perception and stale-world safety

Perception observations are data, not authorization. Confidence does not imply verification and model output cannot override permissions, approvals, e-stop, ROS2 safety limits, or independent action verification. Robot/device identity is registered before observations are accepted; mismatched or unknown identities and malformed observations are rejected. Freshness is recomputed from the source timestamp after restart, conflicting fresh sources do not silently overwrite current world state, and integrated simulated motion requires fresh perception before the normal action gates. Physical sensor claims are never inferred from simulation provenance.

## Operations surface security

The Personal Operations Surface is read-only aggregation. Device scopes redact approval, notification, device and world-state sections when the authenticated client lacks those capabilities. Approval controls call the existing `decide_approval` and original-goal `resume` path; they do not invoke write tools directly, so exact approval scope, risk policy, verification and tracing remain authoritative. Raw approval scope, secret-named fields, secret-like credential values and hidden reasoning are excluded from the projection.

## Notification intelligence security

Notification intelligence is non-authoritative for execution: it cannot approve actions, create grants, run tools, alter robot/e-stop state, or activate providers. Candidates and decisions retain bounded source/correlation provenance while filtering secret-named fields, raw content, requested approval scope, authorization material and hidden-reasoning fields. Owner isolation applies to inspection, explanation, attention listing and state mutation. Attention priority is not execution privilege.
## Advisory NVIDIA content safety

The routed `safety` capability is advisory only. `SafetyModelRuntime` blocks external transmission for SENSITIVE, HIGHLY_SENSITIVE, and DEVICE_CONTROL classifications by default and persists only the advisory result plus provider/model/request/reference/timestamp provenance. `PolicyEngine.evaluate_with_advisory` is monotonic: safe advice cannot grant anything; flagged advice may escalate a deterministic ALLOW to REQUIRE_APPROVAL, while existing REQUIRE_APPROVAL and DENY decisions remain authoritative. Approval, secret, workspace, device-control, ROS2 and e-stop boundaries are not delegated to the model.

## Notification delivery security

Notification delivery does not create authority and cannot change Notification Intelligence decisions. Browser desktop delivery requires an authenticated Personal Core device with the existing `notifications` scope plus an explicit browser-reported permission state; the backend cannot self-grant browser notification permission. Channel result and acknowledgement callbacks are owner- and target-device-bound. PersonalAgent inspection is read-only, while delivery retry and acknowledgement are registered as state-changing capabilities and therefore use the normal Gen-2 approval path. Direct PWA acknowledgement/result callbacks remain bounded to the already-authenticated notification device scope, analogous to the existing mark-read boundary.

Desktop payloads are short bounded projections. Secret-like values are redacted, and notifications carrying SENSITIVE, HIGHLY_SENSITIVE, or DEVICE_CONTROL provenance use a generic protected title/body and only a notification reference. Raw authorization material, hidden reasoning, private prompts, requested approval scopes, and arbitrary protected application state are not copied into desktop payloads. Voice/mobile unavailable states never trigger external delivery. Revoked browser devices are treated as unavailable even if an older channel state had reported granted permission.

## Voice privacy and authorization

Voice input has no special authority. A final provider transcript is dispatched through the same `ConversationService -> PersonalAgent` boundary as typed text, so permission, risk, approval, scoped delegation grants, independent verification, device/robot policy, and e-stop behavior are unchanged. Provider-generated speech received before that PersonalAgent boundary is rejected rather than played as an authorized SPARKLE response.

Raw microphone/audio chunks are never written to the voice event/session store by default. Persisted event schemas reject raw audio and secret/token/authorization fields. SENSITIVE, HIGHLY_SENSITIVE, and DEVICE_CONTROL classifications are denied external VoiceChat transmission unless an explicit future policy changes that boundary. Provider credentials remain secret references only. The production VoiceChat adapter refuses use while the documented NVCF streaming transport is unverified; it does not guess a direct endpoint and there is no STT/LLM/TTS fallback.

## Image generation privacy and artifact safety

Image generation is a state-changing/external action and therefore uses normal Gen-2 human approval with exact tool/argument scope. Model-supplied `approved`, `approval_id`, or `grant_id` fields are rejected, and any approved prompt/size/seed/steps/classification mutation fails scope reconciliation. SENSITIVE, HIGHLY_SENSITIVE, and DEVICE_CONTROL prompts are rejected before an external provider call. Persisted artifact manifests contain a prompt SHA-256 rather than raw prompt text and never contain API keys or authorization headers.

Provider responses are untrusted: Gen-2 requires exactly one bounded artifact, strict base64, a supported JPEG/PNG signature, bounded decoded bytes, finite/integer seed metadata, and independently parses the local image container/dimensions after decoding. Generated images are passive artifacts only; their contents do not grant authority or trigger execution. Artifact files remain inside the existing private ArtifactManager root and must pass a second filesystem/digest reread before the PersonalAgent step can verify or complete.
## Connector security boundary

`ConnectorManager` is not an authorization authority. Each operation maps to the existing deterministic Gen-2 policy capability and receives `ALLOW`, `REQUIRE_APPROVAL`, or `DENY` from `PolicyEngine`. PersonalAgent connector mutations additionally require the normal exact-scope approval record. `approved`, `approval_id`, `grant_id`, `authorization_override`, tokens, cookies, and similar authority-bearing fields are rejected when supplied inside connector arguments; only trusted server-side approval objects can satisfy an approval requirement. Approval cannot compensate for missing connector authorization, wrong owner/device identity, revoked/expired state, or an unavailable adapter.

Connector state and invocation records are owner-scoped. Device-scoped connectors require a device identity on invocation and continue to rely on their existing device/safety boundary. ROS 2 commands stay behind the existing ROS2 gateway, bounded motion policy, verification, and independent e-stop; ConnectorManager adds no direct motor path. Protected `SENSITIVE`, `HIGHLY_SENSITIVE`, and `DEVICE_CONTROL` content is denied before transmission through connectors declared as external dependencies.

Connector descriptors contain only symbolic secret references such as `GOOGLE_OAUTH_TOKEN`, `MICROSOFT_GRAPH_TOKEN`, or `GITHUB_TOKEN`. Secret values are resolved outside persisted connector state. Stored invocation provenance contains provider/system identity, policy capability, request correlation, bounded result shape, external reference when safe, and verification status; it does not store credential values, access/refresh tokens, authorization headers, cookies, hidden reasoning, or raw external payloads. External OAuth authorization flows are intentionally not implemented in this cycle.

After restart, persisted lifecycle/authorization records remain available, but live connection/health is not inferred from persistence alone. Adapters must be registered again and health rechecked. Descriptor-only external connectors therefore remain unavailable/external-blocked after restart rather than becoming implicitly connected.
