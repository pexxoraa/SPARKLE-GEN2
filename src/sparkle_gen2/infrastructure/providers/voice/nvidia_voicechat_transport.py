from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sparkle.model import ModelError
from sparkle.secrets import SecretNotFoundError, SecretResolver

HOSTED_GATEWAY_HOST = "api.ngc.nvidia.com"
HOSTED_GATEWAY_PATH = "/v2/predict/artifactname/websocket/v1/realtime"
CLIENT_SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
ENCODING = "pcm_s16le"
MAX_EVENT_BYTES = 4_000_000
MAX_AUDIO_CHUNK_BYTES = 64_000
MAX_TRANSCRIPT_CHARS = 16_000
PERSONAL_AGENT_TOOL = "sparkle_personal_agent"


def hosted_voicechat_url(function_id: str) -> str:
    try:
        parsed = uuid.UUID(str(function_id))
    except (ValueError, AttributeError):
        raise ValueError("voicechat function_id must be a UUID") from None
    return (
        f"wss://{HOSTED_GATEWAY_HOST}"
        f"{HOSTED_GATEWAY_PATH}?nv-function-id={parsed}"
    )


def validate_hosted_voicechat_url(value: str, function_id: str) -> str:
    expected = hosted_voicechat_url(function_id)
    parsed = urlsplit(str(value))
    if (
        parsed.scheme != "wss"
        or parsed.hostname != HOSTED_GATEWAY_HOST
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.path != HOSTED_GATEWAY_PATH
    ):
        raise ValueError("voicechat hosted endpoint is not allowlisted")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"nv-function-id"} or query["nv-function-id"] != [str(uuid.UUID(str(function_id)))]:
        raise ValueError("voicechat hosted endpoint function identity mismatch")
    if value != expected:
        raise ValueError("voicechat hosted endpoint must use canonical NVIDIA Build gateway form")
    return value


@dataclass(slots=True)
class _Session:
    reference: str
    sparkle_session_id: str
    websocket: Any
    provider_session_id: str | None = None
    pending_call_id: str | None = None
    pending_call_arguments: dict[str, Any] | None = None
    user_transcript_parts: list[str] = field(default_factory=list)
    assistant_transcript_parts: list[str] = field(default_factory=list)
    pre_authorization_audio_bytes: int = 0
    closed: bool = False


class NVIDIAHostedVoiceChatTransport:
    """Strict NVIDIA Build/NVCF realtime VoiceChat client.

    This transport implements the NVIDIA-authored realtime event contract while
    preserving the SPARKLE authorization boundary: provider audio is never
    returned before the model delegates through the single PersonalAgent tool.
    """

    def __init__(
        self,
        *,
        function_id: str,
        secrets: SecretResolver,
        secret_refs: list[str] | tuple[str, ...],
        websocket_url: str | None = None,
        connect_timeout: float = 15.0,
        event_timeout: float = 8.0,
        turn_timeout: float = 45.0,
        connector=None,
    ):
        self.function_id = str(uuid.UUID(str(function_id)))
        self.websocket_url = validate_hosted_voicechat_url(
            websocket_url or hosted_voicechat_url(self.function_id), self.function_id
        )
        self._secrets = secrets
        self._secret_refs = tuple(secret_refs)
        self._connect_timeout = max(1.0, min(float(connect_timeout), 30.0))
        self._event_timeout = max(0.1, min(float(event_timeout), 15.0))
        self._turn_timeout = max(5.0, min(float(turn_timeout), 90.0))
        self._connector = connector
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    @staticmethod
    def _personal_agent_tool() -> dict[str, Any]:
        return {
            "type": "function",
            "name": PERSONAL_AGENT_TOOL,
            "description": (
                "Send every user request to the SPARKLE PersonalAgent for "
                "policy-controlled planning, approval, execution, and verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {"request": {"type": "string"}},
                "required": ["request"],
                "additionalProperties": False,
            },
        }

    @staticmethod
    def _instructions() -> str:
        return (
            "For every user utterance, do not answer or act directly. "
            f"Call {PERSONAL_AGENT_TOOL} exactly once with the user's request. "
            "Wait for the function result. Only after the function result arrives, "
            "speak the verified result. Never invent tool results or approvals."
        )

    def _key(self) -> str:
        try:
            return self._secrets.first(self._secret_refs)
        except SecretNotFoundError:
            raise ModelError(
                "NVIDIA VoiceChat credential is not configured",
                retryable=False,
                category="configuration_failure",
            ) from None

    def _connect(self):
        if self._connector is not None:
            return self._connector(
                self.websocket_url,
                additional_headers={"Authorization": "Bearer " + self._key()},
                open_timeout=self._connect_timeout,
                close_timeout=5,
                max_size=MAX_EVENT_BYTES,
            )
        try:
            from websockets.sync.client import connect
        except Exception as exc:
            raise ModelError(
                "websockets runtime is unavailable",
                retryable=False,
                category="configuration_failure",
            ) from exc
        return connect(
            self.websocket_url,
            additional_headers={"Authorization": "Bearer " + self._key()},
            open_timeout=self._connect_timeout,
            close_timeout=5,
            max_size=MAX_EVENT_BYTES,
        )

    @staticmethod
    def _decode_event(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ModelError(
                "NVIDIA VoiceChat returned an invalid realtime frame",
                retryable=False,
                category="malformed_response",
            )
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise ModelError(
                "NVIDIA VoiceChat returned invalid JSON",
                retryable=False,
                category="malformed_response",
            ) from None
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ModelError(
                "NVIDIA VoiceChat event schema is invalid",
                retryable=False,
                category="malformed_response",
            )
        event_id = value.get("event_id")
        if event_id is not None and (not isinstance(event_id, str) or len(event_id) > 128):
            raise ModelError(
                "NVIDIA VoiceChat event_id is invalid",
                retryable=False,
                category="malformed_response",
            )
        return value

    def _recv(self, session: _Session, timeout: float | None = None) -> dict[str, Any]:
        try:
            raw = session.websocket.recv(timeout=timeout or self._event_timeout)
        except TimeoutError:
            raise
        except Exception as exc:
            raise ModelError(
                "NVIDIA VoiceChat realtime connection failed",
                retryable=True,
                category="connectivity_failure",
            ) from exc
        event = self._decode_event(raw)
        if event["type"] == "error":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            code = str(error.get("code") or "provider_error")[:128]
            raise ModelError(
                f"NVIDIA VoiceChat provider error: {code}",
                retryable=code in {"inference_timeout", "session_timeout"},
                category="provider_failure",
            )
        return event

    @staticmethod
    def _format_rate(session: dict[str, Any], direction: str) -> int | None:
        try:
            fmt = session["audio"][direction]["format"]
        except (KeyError, TypeError):
            return None
        if isinstance(fmt, dict):
            rate = fmt.get("rate")
            return rate if isinstance(rate, int) and not isinstance(rate, bool) else None
        return CLIENT_SAMPLE_RATE if fmt == "pcm16" else None

    def open_session(self, session: dict[str, Any]) -> str:
        sparkle_id = str(session.get("session_id") or "")
        if not sparkle_id or len(sparkle_id) > 128:
            raise ValueError("voicechat session_id is invalid")
        requested_in = dict(session.get("input_audio") or {})
        requested_out = dict(session.get("output_audio") or {})
        for value, label in ((requested_in, "input"), (requested_out, "output")):
            if (
                value.get("sample_rate") != CLIENT_SAMPLE_RATE
                or value.get("channels") != CHANNELS
                or value.get("sample_width") != SAMPLE_WIDTH
                or value.get("encoding") != ENCODING
            ):
                raise ValueError(f"voicechat {label} audio must be 24 kHz mono PCM16")
        ws = self._connect()
        reference = "nvcf_" + uuid.uuid4().hex
        state = _Session(reference, sparkle_id, ws)
        try:
            created = self._recv(state, self._connect_timeout)
            if created["type"] != "session.created":
                raise ModelError(
                    "NVIDIA VoiceChat did not begin with session.created",
                    retryable=False,
                    category="malformed_response",
                )
            provider_session = created.get("session") if isinstance(created.get("session"), dict) else {}
            state.provider_session_id = str(provider_session.get("id") or "") or None
            update = {
                "type": "session.update",
                "event_id": str(uuid.uuid4()),
                "session": {
                    "audio": {
                        "input": {"format": {"type": "audio/pcm", "rate": CLIENT_SAMPLE_RATE}},
                        "output": {"format": {"type": "audio/pcm", "rate": CLIENT_SAMPLE_RATE}},
                    },
                    "instructions": self._instructions(),
                    "tools": [self._personal_agent_tool()],
                    "tool_choice": "required",
                },
            }
            ws.send(json.dumps(update, separators=(",", ":")))
            updated = self._recv(state, self._connect_timeout)
            if updated["type"] != "session.updated":
                raise ModelError(
                    "NVIDIA VoiceChat did not acknowledge session.update",
                    retryable=False,
                    category="malformed_response",
                )
            effective = updated.get("session") if isinstance(updated.get("session"), dict) else {}
            if (
                self._format_rate(effective, "input") != CLIENT_SAMPLE_RATE
                or self._format_rate(effective, "output") != CLIENT_SAMPLE_RATE
            ):
                raise ModelError(
                    "NVIDIA VoiceChat negotiated an unexpected audio format",
                    retryable=False,
                    category="protocol_mismatch",
                )
            tools = effective.get("tools")
            if isinstance(tools, str):
                try:
                    tools = json.loads(tools)
                except json.JSONDecodeError:
                    tools = None
            if not isinstance(tools, list) or not any(
                isinstance(x, dict) and x.get("name") == PERSONAL_AGENT_TOOL for x in tools
            ):
                raise ModelError(
                    "NVIDIA VoiceChat did not retain the PersonalAgent tool",
                    retryable=False,
                    category="protocol_mismatch",
                )
        except Exception:
            try:
                ws.close()
            except Exception:
                pass
            raise
        with self._lock:
            self._sessions[reference] = state
        return reference

    def _session(self, reference: str) -> _Session:
        with self._lock:
            state = self._sessions.get(str(reference))
        if state is None or state.closed:
            raise RuntimeError("voicechat provider session is unavailable")
        return state

    @staticmethod
    def _safe_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        value = value.strip()
        if len(value) > MAX_TRANSCRIPT_CHARS:
            raise ModelError(
                "NVIDIA VoiceChat transcript exceeds limit",
                retryable=False,
                category="malformed_response",
            )
        return value

    def _consume_pre_authorization(self, state: _Session, *, final: bool) -> dict[str, Any]:
        transcripts: list[dict[str, Any]] = []
        if not final:
            deadline = time.monotonic() + 0.05
        else:
            deadline = time.monotonic() + self._turn_timeout
        saw_final_user = False
        while time.monotonic() < deadline:
            remaining = max(0.01, min(self._event_timeout, deadline - time.monotonic()))
            try:
                event = self._recv(state, remaining)
            except TimeoutError:
                if not final:
                    break
                continue
            kind = event["type"]
            if kind == "conversation.item.input_audio_transcription.delta":
                text = self._safe_text(event.get("delta"))
                if text:
                    state.user_transcript_parts.append(text)
            elif kind == "conversation.item.input_audio_transcription.completed":
                text = self._safe_text(event.get("transcript")) or "".join(state.user_transcript_parts).strip()
                if text:
                    transcripts.append(
                        {
                            "speaker": "user",
                            "text": text,
                            "final": True,
                            "provider_reference": event.get("item_id"),
                        }
                    )
                    saw_final_user = True
            elif kind == "response.function_call_arguments.done":
                name = str(event.get("name") or "")
                call_id = str(event.get("call_id") or "")
                arguments = event.get("arguments")
                if name != PERSONAL_AGENT_TOOL or not call_id:
                    raise PermissionError("voicechat provider requested an unauthorized function")
                try:
                    parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
                except json.JSONDecodeError:
                    raise PermissionError("voicechat function arguments are malformed") from None
                if not isinstance(parsed, dict) or set(parsed) != {"request"} or not isinstance(parsed.get("request"), str):
                    raise PermissionError("voicechat function arguments exceed PersonalAgent scope")
                state.pending_call_id = call_id
                state.pending_call_arguments = parsed
            elif kind == "response.output_audio.delta":
                encoded = event.get("delta")
                if not isinstance(encoded, str):
                    raise ModelError("voicechat audio delta is invalid", retryable=False, category="malformed_response")
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except Exception:
                    raise ModelError("voicechat audio delta is invalid", retryable=False, category="malformed_response") from None
                state.pre_authorization_audio_bytes += len(chunk)
            elif kind in {
                "response.created",
                "response.output_item.added",
                "response.content_part.added",
                "response.output_audio_transcript.delta",
                "response.output_audio_transcript.done",
                "response.output_text.delta",
                "response.output_text.done",
                "input_audio_buffer.speech_started",
                "input_audio_buffer.speech_stopped",
            }:
                pass
            elif kind in {"response.done", "response.output_audio.done", "response.content_part.done", "response.output_item.done"}:
                pass
            elif kind == "session.end":
                state.closed = True
                raise ModelError("NVIDIA VoiceChat session ended before authorization", retryable=True, category="provider_failure")
            else:
                raise ModelError(
                    f"NVIDIA VoiceChat returned unsupported event: {kind}",
                    retryable=False,
                    category="protocol_mismatch",
                )
            if final and saw_final_user and state.pending_call_id:
                break
        if final and saw_final_user and not state.pending_call_id:
            raise PermissionError("voicechat provider did not delegate to PersonalAgent")
        return {
            "transcripts": transcripts,
            "audio_chunks": [],
            "provider_request_id": state.provider_session_id,
            "final": bool(saw_final_user),
            "pre_authorization_audio_bytes": state.pre_authorization_audio_bytes,
        }

    def send_audio(self, provider_session_reference: str, frame) -> dict[str, Any]:
        state = self._session(provider_session_reference)
        if (
            int(getattr(frame, "sample_rate", 0)) != CLIENT_SAMPLE_RATE
            or int(getattr(frame, "channels", 0)) != CHANNELS
            or int(getattr(frame, "sample_width", 0)) != SAMPLE_WIDTH
            or str(getattr(frame, "encoding", "")) != ENCODING
        ):
            raise ValueError("voicechat input frame must be 24 kHz mono PCM16")
        audio = bytes(getattr(frame, "audio", b""))
        if not audio or len(audio) > MAX_AUDIO_CHUNK_BYTES or len(audio) % 2:
            raise ValueError("voicechat input frame is invalid")
        state.websocket.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "event_id": str(uuid.uuid4()),
                    "audio": base64.b64encode(audio).decode("ascii"),
                },
                separators=(",", ":"),
            )
        )
        return self._consume_pre_authorization(state, final=bool(getattr(frame, "final", False)))

    def respond_text(self, provider_session_reference: str, text: str) -> dict[str, Any]:
        state = self._session(provider_session_reference)
        if not state.pending_call_id:
            raise PermissionError("voicechat PersonalAgent delegation is not pending")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TRANSCRIPT_CHARS:
            raise ValueError("voicechat PersonalAgent result is invalid")
        output = json.dumps({"status": "COMPLETED", "text": text.strip()}, separators=(",", ":"))
        state.websocket.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": state.pending_call_id,
                        "output": output,
                    },
                },
                separators=(",", ":"),
            )
        )
        state.pending_call_id = None
        state.pending_call_arguments = None
        audio_chunks = []
        transcripts = []
        sequence = 0
        saw_terminal_text = False
        deadline = time.monotonic() + self._turn_timeout
        while time.monotonic() < deadline:
            try:
                event = self._recv(state, min(self._event_timeout, max(0.01, deadline - time.monotonic())))
            except TimeoutError:
                if audio_chunks and saw_terminal_text:
                    break
                continue
            kind = event["type"]
            if kind == "response.output_audio.delta":
                try:
                    audio = base64.b64decode(str(event.get("delta") or ""), validate=True)
                except Exception:
                    raise ModelError("voicechat audio delta is invalid", retryable=False, category="malformed_response") from None
                if not audio or len(audio) > MAX_AUDIO_CHUNK_BYTES or len(audio) % 2:
                    raise ModelError("voicechat audio delta is invalid", retryable=False, category="malformed_response")
                audio_chunks.append(
                    {
                        "sequence": sequence,
                        "audio": audio,
                        "sample_rate": CLIENT_SAMPLE_RATE,
                        "channels": CHANNELS,
                        "sample_width": SAMPLE_WIDTH,
                        "encoding": ENCODING,
                        "final": False,
                        "provider_reference": event.get("response_id"),
                    }
                )
                sequence += 1
            elif kind in {"response.output_audio_transcript.delta", "response.output_text.delta"}:
                pass
            elif kind == "response.output_audio_transcript.done":
                value = self._safe_text(event.get("transcript"))
                if value:
                    transcripts.append(
                        {
                            "speaker": "assistant",
                            "text": value,
                            "final": True,
                            "provider_reference": event.get("response_id"),
                        }
                    )
                saw_terminal_text = True
            elif kind == "response.output_text.done":
                value = self._safe_text(event.get("text"))
                if value and not transcripts:
                    transcripts.append(
                        {
                            "speaker": "assistant",
                            "text": value,
                            "final": True,
                            "provider_reference": event.get("response_id"),
                        }
                    )
                saw_terminal_text = True
            elif kind in {
                "response.created",
                "response.output_item.added",
                "response.content_part.added",
                "response.output_audio.done",
                "response.content_part.done",
                "response.output_item.done",
                "response.done",
                "input_audio_buffer.speech_started",
                "input_audio_buffer.speech_stopped",
                "conversation.item.input_audio_transcription.delta",
                "conversation.item.input_audio_transcription.completed",
            }:
                if kind == "response.done" and audio_chunks:
                    break
            elif kind == "response.function_call_arguments.done":
                raise PermissionError("voicechat attempted nested function delegation")
            elif kind == "session.end":
                state.closed = True
                break
            else:
                raise ModelError(
                    f"NVIDIA VoiceChat returned unsupported event: {kind}",
                    retryable=False,
                    category="protocol_mismatch",
                )
            if audio_chunks and saw_terminal_text:
                break
        if not audio_chunks:
            raise ModelError("NVIDIA VoiceChat returned no authorized response audio", retryable=True, category="provider_failure")
        audio_chunks[-1]["final"] = True
        return {
            "transcripts": transcripts,
            "audio_chunks": audio_chunks,
            "provider_request_id": state.provider_session_id,
            "final": True,
        }

    def interrupt(self, provider_session_reference: str) -> dict[str, Any]:
        # The NVIDIA VoiceChat API reference documents full-duplex interruption
        # behavior but no client-side response.cancel event for VoiceChat. Do not
        # invent one. Fail closed until the provider exposes an explicit control.
        self._session(provider_session_reference)
        return {"interrupted": False, "reason": "provider_explicit_interrupt_control_unverified"}

    def close_session(self, provider_session_reference: str) -> dict[str, Any]:
        state = self._session(provider_session_reference)
        try:
            state.websocket.send(
                json.dumps(
                    {"type": "session.close", "event_id": str(uuid.uuid4())},
                    separators=(",", ":"),
                )
            )
            deadline = time.monotonic() + min(self._event_timeout, 5.0)
            while time.monotonic() < deadline:
                try:
                    event = self._recv(state, max(0.01, deadline - time.monotonic()))
                except TimeoutError:
                    break
                if event["type"] == "session.end":
                    break
        finally:
            state.closed = True
            try:
                state.websocket.close()
            finally:
                with self._lock:
                    self._sessions.pop(provider_session_reference, None)
        return {"closed": True}
