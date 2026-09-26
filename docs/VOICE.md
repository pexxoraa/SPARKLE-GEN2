# Voice

SPARKLE Gen-2 exposes one provider-neutral `VoiceSessionService` over the existing `ConversationService -> PersonalAgent -> policy -> approval -> execution -> independent verification` path. Voice providers implement the shared `VoiceProvider` contract; provider output never grants authority.

## Provider selection

The packaged registry contains both voice providers:

- Google Gemini Live: `google-gemini-3.8-live` / model `gemini-3.8-live`.
- NVIDIA Nemotron VoiceChat: `nvidia-nemotron-voicechat`.

The default `voice` route is Gemini. `VOICE_PROVIDER=gemini` or `VOICE_PROVIDER=nvidia` can select a provider explicitly. Fallback remains disabled, so an unavailable selected provider is reported unavailable rather than silently switching providers.

Gemini is `LIVE_ACCEPTED`. NVIDIA remains registered and independently transport-observed, but its hosted Build deployment is still fail-closed because it did not honor the required PersonalAgent function delegation during live probes. Gemini acceptance does not change NVIDIA's gate.

## Gemini Live contract

Gemini uses the official `google-genai` SDK and stable `gemini-3.8-live` model. SPARKLE's provider-neutral voice frames remain 24 kHz, mono, little-endian PCM16. The Gemini boundary alone converts incoming SPARKLE audio to the provider's verified 16 kHz PCM16 input. Gemini output is validated as 24 kHz mono PCM16 before it is returned to callers.

Each Live session enables input transcription, output transcription, AUDIO response modality, and one authorization-sensitive function:

`sparkle_personal_agent`

That function is declared with `behavior: BLOCKING` and has no model-controlled action or authorization arguments. Gemini cannot provide approval IDs, grant IDs, worker identities, credentials, policy overrides, or action scope through the function declaration. SPARKLE uses the finalized user audio transcription as the PersonalAgent request.

## Authorization flow

The production flow is:

```text
user audio
→ Gemini Live transcription
→ BLOCKING sparkle_personal_agent call
→ VoiceSessionService validates call/session/replay state
→ PersonalAgent
→ deterministic policy
→ human approval when required
→ exact-scope tool execution
→ independent verification
→ FunctionResponse
→ Gemini continuation
→ final 24 kHz audio
```

Any provider audio observed before authorization is buffered/discarded and is never exposed as the substantive result. A PersonalAgent `WAITING` result leaves the Gemini function call unresolved and returns zero final audio. After human approval, `resume_pending()` resumes the original persisted goal; only its verified result is returned as the FunctionResponse.

Function-call cancellation, duplicate/replayed call IDs, overlapping calls, unexpected function names, and any non-empty model-controlled arguments fail closed. Active Live sessions are isolated by SPARKLE session identity and are not resumed across process restart.

## Interruption and lifecycle

Gemini interruption uses documented Live API behavior: `send_client_content(turn_complete=True)` interrupts active generation, queued provider audio is discarded, and documented `tool_call_cancellation` IDs invalidate pending calls. A cancelled or interrupted tool call cannot later release a stale FunctionResponse. Disconnects and receive timeouts remain bounded failures; the receive loop tolerates short realtime quiet intervals while enforcing the overall turn deadline.

Personal Core exposes authenticated voice endpoints for status, session creation/inspection, audio frames, interruption, and close. Raw microphone audio is never persisted. Transcript persistence is a per-session choice; acceptance also exercised `persist_transcript=false`.

## Secret handling and configuration

`GEMINI_API_KEY` is an explicit protected secret reference. The accepted workstation configuration stores it in owner-only `~/.config/sparkle/gen2.env` with mode `0600`; the key value is never written to the repository, model prompts, tool arguments, traces, or documentation. `VOICE_PROVIDER=gemini` is stored alongside it as a non-secret provider setting.

## Live acceptance — 2026-09-22

Fresh SPARKLE-side evidence, separate from the prior standalone provider test, proved:

- Safe time-tool transport was freshly revalidated after receive-queue hardening: real transcription, validated BLOCKING function call, FunctionResponse, zero pre-authorization audio exposed, and 140,160 bytes of 24 kHz Gemini audio.
- A real provider-selected `VoiceSessionService → PersonalAgent` run completed a non-destructive SPARKLE tool path with independent verification, fallback disabled, no raw-audio persistence, and 128,160 bytes of final 24 kHz Gemini audio.
- Approval-sensitive notification acknowledgement was freshly revalidated after exact-scope hardening: PersonalAgent returned `WAITING`, exactly one approval was required, the persisted scope contained the exact notification attempt identity, zero final audio was returned before approval, the approved action resumed to independent verification, and Gemini returned 61,440 bytes of 24 kHz audio afterward.
- The authenticated Personal Core HTTP path was freshly revalidated with temporary device enrollment, VoiceSession creation, streamed audio, a real calculator action, independent verification, session inspection, and clean close. It returned 88,320 bytes of final 24 kHz Gemini audio. Persisted voice events contained no forbidden secret/audio fields and no input-audio payload; the session provenance remained `raw_audio_persisted=false`.
- The production SDK runner continuously drains Gemini Live server messages into an isolated per-session queue. Cancellation, replay, or overlapping function calls that arrive while PersonalAgent or human approval is pending are therefore checked before any FunctionResponse can be sent. Post-approval argument mutation is also rejected by the PersonalAgent exact-scope approval binding before execution.

## PWA voice client

The Personal Core PWA now exposes the accepted voice route instead of a stale disabled control. Browser capture is bounded to 30 seconds, held in memory only, resampled to SPARKLE's 24 kHz mono PCM16 frame contract, and sent through authenticated VoiceSession endpoints. Approval-sensitive voice turns remain silent while `WAITING`; either approval surface resumes the exact persisted goal and only the authorized provider continuation is returned for playback. Static audio uploads to `/api/multimodal` remain intentionally separate and direct callers to the realtime VoiceSession API rather than creating a second voice execution path.
