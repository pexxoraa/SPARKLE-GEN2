from __future__ import annotations

import array
import asyncio
import concurrent.futures
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sparkle.model import ModelAdapter, ModelError, ModelRequest, ModelResponse
from sparkle.secrets import SecretNotFoundError, SecretResolver

GEMINI_LIVE_MODEL = "gemini-3.8-live"
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
SPARKLE_INPUT_RATE = 24000
PERSONAL_AGENT_TOOL = "sparkle_personal_agent"
ENCODING = "pcm_s16le"
MAX_AUDIO_CHUNK_BYTES = 64_000
MAX_TRANSCRIPT_CHARS = 16_000
MAX_RESPONSE_AUDIO_BYTES = 4_320_000


def _resample_pcm16(data: bytes, source_rate: int, target_rate: int) -> bytes:
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) % 2:
        raise ValueError("voice audio must be non-empty aligned PCM16")
    if source_rate == target_rate:
        return bytes(data)
    samples = array.array("h")
    samples.frombytes(bytes(data))
    if sys.byteorder != "little":
        samples.byteswap()
    count = max(1, round(len(samples) * target_rate / source_rate))
    output = array.array("h")
    for index in range(count):
        position = index * source_rate / target_rate
        left = int(position)
        fraction = position - left
        a = samples[min(left, len(samples) - 1)]
        b = samples[min(left + 1, len(samples) - 1)]
        output.append(int(a + (b - a) * fraction))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


class _AsyncLoop:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._serve, daemon=True, name="sparkle-gemini-live"
        )
        self.thread.start()
    def _serve(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coroutine, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=max(0.1, float(timeout)))
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("Gemini Live operation timed out") from exc

    def close(self):
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


class _GoogleGenAILiveRunner:
    """Synchronous facade around Google's official asynchronous Live SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        config: dict[str, Any],
        model: str = GEMINI_LIVE_MODEL,
        connect_timeout: float = 30.0,
        turn_timeout: float = 45.0,
    ):
        self._api_key = api_key
        self._config = dict(config)
        self._model = model
        self._connect_timeout = float(connect_timeout)
        self._turn_timeout = float(turn_timeout)
        self._runtime = _AsyncLoop()
        self._client = None
        self._context = None
        self._session = None
        self._receiver_task = None
        self._messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._closed = False
        self._runtime.run(self._open(), self._connect_timeout)

    async def _open(self):
        try:
            from google import genai
        except Exception as exc:
            raise ModelError(
                "google-genai runtime is unavailable",
                retryable=False,
                category="configuration_failure",
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        self._context = self._client.aio.live.connect(
            model=self._model, config=self._config
        )
        self._session = await self._context.__aenter__()
        self._receiver_task = asyncio.create_task(self._receive_forever())

    async def _receive_forever(self):
        try:
            while not self._closed:
                async for message in self._session.receive():
                    self._messages.put(("message", message))
                if not self._closed:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            if not self._closed:
                self._messages.put(("error", exc))

    @staticmethod
    def _unwrap(item: tuple[str, Any]):
        kind, value = item
        if kind == "message":
            return value
        if isinstance(value, TimeoutError):
            raise value
        raise ModelError(
            "Gemini Live receive failed",
            retryable=True,
            category="connectivity_failure",
        ) from value

    def start_activity(self):
        from google.genai import types
        self._runtime.run(
            self._session.send_realtime_input(activity_start=types.ActivityStart()),
            self._connect_timeout,
        )

    def send_audio(self, audio: bytes):
        from google.genai import types
        blob = types.Blob(data=bytes(audio), mime_type="audio/pcm;rate=16000")
        self._runtime.run(
            self._session.send_realtime_input(audio=blob), self._connect_timeout
        )

    def end_audio(self):
        from google.genai import types
        self._runtime.run(
            self._session.send_realtime_input(activity_end=types.ActivityEnd()),
            self._connect_timeout,
        )

    def send_text(self, text: str):
        from google.genai import types
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=str(text))],
        )
        self._runtime.run(
            self._session.send_client_content(turns=content, turn_complete=True),
            self._connect_timeout,
        )

    def recv(self, timeout: float):
        try:
            item = self._messages.get(timeout=max(0.01, float(timeout)))
        except queue.Empty as exc:
            raise TimeoutError("Gemini Live receive timed out") from exc
        return self._unwrap(item)

    def recv_nowait(self):
        try:
            item = self._messages.get_nowait()
        except queue.Empty:
            return None
        return self._unwrap(item)

    def send_tool_response(self, call_id: str, name: str, text: str):
        from google.genai import types
        response = types.FunctionResponse(
            id=call_id, name=name, response={"result": text}
        )
        self._runtime.run(
            self._session.send_tool_response(function_responses=[response]),
            self._connect_timeout,
        )

    def stop_generation(self, timeout: float = 0.8):
        self._runtime.run(
            self._session.send_client_content(turn_complete=True),
            self._connect_timeout,
        )
        deadline = time.monotonic() + max(0.2, min(float(timeout), 2.0))
        while time.monotonic() < deadline:
            try:
                message = self.recv(min(0.1, deadline - time.monotonic()))
            except TimeoutError:
                continue
            content = getattr(message, "server_content", None)
            if content is not None and (
                bool(getattr(content, "interrupted", False))
                or bool(getattr(content, "turn_complete", False))
            ):
                break
        self.drain()

    def interrupt(self):
        self.stop_generation(timeout=1.2)

    def drain(self):
        count = 0
        while True:
            try:
                self._messages.get_nowait()
            except queue.Empty:
                break
            count += 1
        return count

    def close(self):
        async def shutdown():
            self._closed = True
            if self._receiver_task is not None:
                self._receiver_task.cancel()
                try:
                    await self._receiver_task
                except asyncio.CancelledError:
                    pass
            if self._context is not None:
                await self._context.__aexit__(None, None, None)
        try:
            self._runtime.run(shutdown(), self._connect_timeout)
        finally:
            self._runtime.close()


@dataclass(slots=True)
class _Session:
    reference: str
    sparkle_session_id: str
    runner: Any | None
    pending_call_id: str | None = None
    completed_call_ids: set[str] = field(default_factory=set)
    cancelled_call_ids: set[str] = field(default_factory=set)
    input_transcript: str = ""
    pre_authorization_audio_bytes: int = 0
    activity_active: bool = False
    awaiting_authorized_response: bool = False
    interrupt_requested: bool = False
    closed: bool = False


class GeminiLiveVoiceTransport:
    """Gemini Live transport with explicit turn boundaries and SPARKLE-owned authorization."""

    def __init__(
        self,
        *,
        secrets: SecretResolver,
        secret_refs: list[str] | tuple[str, ...],
        runner_factory: Callable[..., Any] | None = None,
        model: str = GEMINI_LIVE_MODEL,
        connect_timeout: float = 30.0,
        turn_timeout: float = 45.0,
        tool_name: str = PERSONAL_AGENT_TOOL,
        tool_description: str | None = None,
    ):
        if model != GEMINI_LIVE_MODEL:
            raise ValueError("Gemini voice model must be gemini-3.8-live")
        self._secrets = secrets
        self._secret_refs = tuple(secret_refs)
        self._runner_factory = runner_factory or _GoogleGenAILiveRunner
        self._model = model
        self._connect_timeout = max(2.0, min(float(connect_timeout), 30.0))
        self._turn_timeout = max(5.0, min(float(turn_timeout), 90.0))
        self._tool_name = str(tool_name)
        self._tool_description = tool_description or (
            "Delegate the fully transcribed user request to the SPARKLE "
            "PersonalAgent for policy, approval, execution, and verification."
        )
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.RLock()

    def _key(self) -> str:
        try:
            return self._secrets.first(self._secret_refs)
        except SecretNotFoundError:
            raise ModelError(
                "Gemini credential is not configured",
                retryable=False,
                category="configuration_failure",
            ) from None

    def _config(self) -> dict[str, Any]:
        return {
            "response_modalities": ["AUDIO"],
            "max_output_tokens": 1536,
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "realtime_input_config": {
                "automatic_activity_detection": {"disabled": True},
            },
            "system_instruction": (
                "Use incoming audio only to transcribe the user's request. Do not answer or perform actions "
                "from the microphone turn. SPARKLE owns policy, authorization, execution, and verification. "
                "After SPARKLE explicitly sends authorized response text, speak it naturally. "
                "If authorized text begins with ANSWER_REQUEST:, answer the contained user question naturally "
                "and never execute an action from that request. Keep spoken answers concise: normally 1-2 sentences "
                "and no more than about 45 words unless the authorized text is an execution result."
            ),
        }

    def open_session(self, session: dict[str, Any]) -> str:
        sid = str(session.get("session_id") or "")
        incoming = dict(session.get("input_audio") or {})
        outgoing = dict(session.get("output_audio") or {})
        if not sid or len(sid) > 128:
            raise ValueError("gemini voice session_id is invalid")
        if (
            incoming.get("sample_rate") != SPARKLE_INPUT_RATE
            or incoming.get("channels") != 1
            or incoming.get("sample_width") != 2
            or incoming.get("encoding") != ENCODING
        ):
            raise ValueError("SPARKLE voice input must be 24 kHz mono PCM16")
        if (
            outgoing.get("sample_rate") != GEMINI_OUTPUT_RATE
            or outgoing.get("channels") != 1
            or outgoing.get("sample_width") != 2
            or outgoing.get("encoding") != ENCODING
        ):
            raise ValueError("Gemini voice output must be 24 kHz mono PCM16")
        runner = self._runner_factory(
            api_key=self._key(),
            config=self._config(),
            model=self._model,
            connect_timeout=self._connect_timeout,
            turn_timeout=self._turn_timeout,
        )
        reference = "gemini_" + uuid.uuid4().hex
        with self._lock:
            self._sessions[reference] = _Session(reference, sid, runner)
        return reference

    def _state(self, reference: str) -> _Session:
        with self._lock:
            state = self._sessions.get(str(reference))
        if state is None or state.closed:
            raise RuntimeError("gemini voice session is unavailable")
        return state

    def _new_runner(self):
        return self._runner_factory(
            api_key=self._key(),
            config=self._config(),
            model=self._model,
            connect_timeout=self._connect_timeout,
            turn_timeout=self._turn_timeout,
        )

    @staticmethod
    def _bounded_text(value: Any) -> str:
        text = str(value or "").strip()
        if len(text) > MAX_TRANSCRIPT_CHARS:
            raise ModelError(
                "Gemini transcript exceeds limit",
                retryable=False,
                category="malformed_response",
            )
        return text

    @staticmethod
    def _message_audio(message: Any) -> bytes:
        content = getattr(message, "server_content", None)
        turn = getattr(content, "model_turn", None) if content is not None else None
        parts = list(getattr(turn, "parts", None) or [])
        chunks = []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline is not None else None
            mime = getattr(inline, "mime_type", None) if inline is not None else None
            if data is None:
                continue
            if mime and "audio/pcm" not in str(mime):
                raise ModelError(
                    "Gemini returned unexpected media",
                    retryable=False,
                    category="malformed_response",
                )
            if mime and "rate=" in str(mime) and "rate=24000" not in str(mime):
                raise ModelError(
                    "Gemini returned unexpected audio rate",
                    retryable=False,
                    category="protocol_mismatch",
                )
            if not isinstance(data, (bytes, bytearray)) or len(data) % 2:
                raise ModelError(
                    "Gemini returned invalid PCM audio",
                    retryable=False,
                    category="malformed_response",
                )
            chunks.append(bytes(data))
        if chunks:
            return b"".join(chunks)
        data = getattr(message, "data", None)
        if data is None:
            return b""
        if not isinstance(data, (bytes, bytearray)) or len(data) % 2:
            raise ModelError(
                "Gemini returned invalid PCM audio",
                retryable=False,
                category="malformed_response",
            )
        return bytes(data)

    def _accept_tool_call(self, state: _Session, message: Any) -> bool:
        call = getattr(message, "tool_call", None)
        if call is None:
            return False
        calls = list(getattr(call, "function_calls", None) or [])
        if len(calls) != 1:
            raise PermissionError("gemini voice requires exactly one function call")
        item = calls[0]
        call_id = str(getattr(item, "id", "") or "")
        name = str(getattr(item, "name", "") or "")
        args = getattr(item, "args", None)
        if name != self._tool_name or not call_id:
            raise PermissionError("gemini voice requested an unauthorized function")
        if call_id in state.completed_call_ids or call_id == state.pending_call_id:
            raise PermissionError("gemini voice duplicate function call")
        if args not in (None, {}) and dict(args or {}):
            raise PermissionError("gemini voice function arguments must be empty")
        state.pending_call_id = call_id
        return True

    def _check_cancellation(self, state: _Session, message: Any):
        cancellation = getattr(message, "tool_call_cancellation", None)
        if cancellation is None:
            return
        ids = {str(x) for x in (getattr(cancellation, "ids", None) or [])}
        if state.pending_call_id and state.pending_call_id in ids:
            state.cancelled_call_ids.add(state.pending_call_id)
            state.pending_call_id = None
            raise RuntimeError("gemini voice pending function call was cancelled")

    @classmethod
    def _merge_transcript(cls, existing: str, incoming: Any) -> str:
        new = cls._bounded_text(incoming)
        current = cls._bounded_text(existing)
        if not new:
            return current
        if not current:
            return new
        if new == current or new.startswith(current + " "):
            return new
        if current.startswith(new + " "):
            return current
        current_words = current.split()
        new_words = new.split()
        overlap = 0
        for size in range(min(len(current_words), len(new_words)), 0, -1):
            if current_words[-size:] == new_words[:size]:
                overlap = size
                break
        return " ".join(current_words + new_words[overlap:])

    def send_audio(self, provider_session_reference: str, frame: Any) -> dict[str, Any]:
        state = self._state(provider_session_reference)
        if state.runner is None:
            state.runner = self._new_runner()
        if (
            int(getattr(frame, "sample_rate", 0)) != SPARKLE_INPUT_RATE
            or int(getattr(frame, "channels", 0)) != 1
            or int(getattr(frame, "sample_width", 0)) != 2
            or str(getattr(frame, "encoding", "")) != ENCODING
        ):
            raise ValueError("SPARKLE voice frame must be 24 kHz mono PCM16")
        converted = _resample_pcm16(
            bytes(getattr(frame, "audio", b"")),
            SPARKLE_INPUT_RATE,
            GEMINI_INPUT_RATE,
        )
        if not state.activity_active:
            state.runner.start_activity()
            state.activity_active = True
        state.runner.send_audio(converted)
        if not bool(getattr(frame, "final", False)):
            return {
                "transcripts": [], "audio_chunks": [],
                "provider_request_id": state.reference, "final": False,
            }
        state.runner.end_audio()
        state.activity_active = False
        deadline = time.monotonic() + min(self._turn_timeout, 8.0)
        transcript_stable_deadline = None
        while time.monotonic() < deadline:
            try:
                message = state.runner.recv(min(0.20, max(0.05, deadline - time.monotonic())))
            except TimeoutError:
                if state.input_transcript and transcript_stable_deadline is not None and time.monotonic() >= transcript_stable_deadline:
                    break
                continue
            self._check_cancellation(state, message)
            audio = self._message_audio(message)
            if audio:
                state.pre_authorization_audio_bytes += len(audio)
            content = getattr(message, "server_content", None)
            if content is not None:
                transcript = getattr(content, "input_transcription", None)
                text = self._bounded_text(getattr(transcript, "text", "") if transcript is not None else "")
                if text:
                    state.input_transcript = self._merge_transcript(state.input_transcript, text)
                    transcript_stable_deadline = time.monotonic() + 0.20
                if bool(getattr(content, "interrupted", False)):
                    break
                if bool(getattr(content, "turn_complete", False)):
                    break
            if state.input_transcript and transcript_stable_deadline is not None and time.monotonic() >= transcript_stable_deadline:
                break
        if not state.input_transcript:
            raise ModelError("Gemini input transcription missing",retryable=True,category="provider_failure")
        final_transcript=state.input_transcript
        # Each microphone turn is independent. Do not carry the previous
        # transcript into the next recognition session, especially when the
        # authorized TTS turn later fails and cannot clear it.
        state.input_transcript = ""
        state.awaiting_authorized_response = True
        # Recognition and speech are deliberately isolated. Closing the input
        # turn here prevents any late recognition/control packets from leaking
        # into the authorized response turn.
        input_runner=state.runner
        if isinstance(input_runner, _GoogleGenAILiveRunner):
            state.runner=None
            try:
                input_runner.close()
            except Exception:
                try: input_runner.drain()
                except Exception: pass
        return {
            "transcripts": [{
                "speaker": "user",
                "text": final_transcript,
                "final": True,
                "provider_reference": state.pending_call_id,
            }],
            "audio_chunks": [],
            "provider_request_id": state.reference,
            "final": True,
            "pre_authorization_audio_bytes": state.pre_authorization_audio_bytes,
        }

    def validate_pending_call(self, provider_session_reference: str) -> dict[str, Any]:
        state = self._state(provider_session_reference)
        if not state.awaiting_authorized_response:
            raise PermissionError("gemini voice has no pending SPARKLE authorization")
        return {"valid": True, "session": state.reference}

    def respond_text(
        self, provider_session_reference: str, text: str
    ) -> dict[str, Any]:
        state = self._state(provider_session_reference)
        state.interrupt_requested = False
        self.validate_pending_call(provider_session_reference)
        value = self._bounded_text(text)
        if not value:
            raise PermissionError("gemini SPARKLE response is not authorized")
        if value.startswith("ANSWER_REQUEST:"):
            value="Answer this authorized user request naturally: "+value.split(":",1)[1].strip()
        state.pending_call_id = None
        state.awaiting_authorized_response = False
        # The recognition transport is discarded before authorization. Start a
        # clean Gemini Live session for the authorized speech turn so no late
        # recognition packets can be mistaken for response audio.
        if state.runner is None:
            state.runner = self._new_runner()
        state.runner.send_text(value)
        chunks = []
        transcript_parts = []
        sequence = 0
        started = time.monotonic()
        deadline = started + self._turn_timeout
        first_audio_deadline = started + min(self._turn_timeout, 15.0)
        completed = False
        audio_bytes = 0
        transcript_chars = 0
        while time.monotonic() < deadline:
            try:
                wait_for=min(0.15, max(0.05, deadline-time.monotonic()))
                if not chunks:
                    wait_for=min(wait_for,max(0.05,first_audio_deadline-time.monotonic()))
                message = state.runner.recv(wait_for)
            except TimeoutError:
                if not chunks and time.monotonic() >= first_audio_deadline:
                    break
                continue
            self._check_cancellation(state, message)
            if getattr(message, "tool_call", None) is not None:
                raise PermissionError("gemini voice attempted nested function execution")
            audio = self._message_audio(message)
            if audio:
                audio_bytes += len(audio)
                if audio_bytes > MAX_RESPONSE_AUDIO_BYTES:
                    raise ModelError("Gemini response audio exceeds bound", retryable=False, category="malformed_response")
                for offset in range(0, len(audio), MAX_AUDIO_CHUNK_BYTES):
                    piece = audio[offset:offset + MAX_AUDIO_CHUNK_BYTES]
                    if piece:
                        chunks.append({
                            "sequence": sequence,
                            "audio": piece,
                            "sample_rate": GEMINI_OUTPUT_RATE,
                            "channels": 1,
                            "sample_width": 2,
                            "encoding": ENCODING,
                            "final": False,
                            "provider_reference": state.reference,
                        })
                        sequence += 1
            content = getattr(message, "server_content", None)
            if content is not None:
                output = getattr(content, "output_transcription", None)
                part = self._bounded_text(getattr(output, "text", "") if output is not None else "")
                if part:
                    transcript_chars += len(part)
                    if transcript_chars > MAX_TRANSCRIPT_CHARS:
                        raise ModelError("Gemini response transcript exceeds bound", retryable=False, category="malformed_response")
                    transcript_parts.append(part)
                if bool(getattr(content, "interrupted", False)):
                    if state.interrupt_requested: raise RuntimeError("gemini voice authorized response was interrupted")
                    continue
                if bool(getattr(content, "turn_complete", False)) and chunks:
                    completed = True
                    break
        if not chunks:
            raise ModelError(
                "Gemini returned no authorized response audio",
                retryable=True,
                category="provider_failure",
            )
        if not completed:
            raise ModelError("Gemini authorized speech turn did not complete within budget", retryable=True, category="timeout")
        chunks[-1]["final"] = True
        transcript = "".join(transcript_parts).strip()
        state.input_transcript = ""
        state.pre_authorization_audio_bytes = 0
        response={
            "transcripts": ([{
                "speaker": "assistant",
                "text": transcript,
                "final": True,
                "provider_reference": state.reference,
            }] if transcript else []),
            "audio_chunks": chunks,
            "provider_request_id": state.reference,
            "final": True,
        }
        if isinstance(state.runner, _GoogleGenAILiveRunner):
            runner=state.runner
            state.runner=None
            try: runner.close()
            except Exception: pass
        return response

    def interrupt(self, provider_session_reference: str) -> dict[str, Any]:
        state = self._state(provider_session_reference)
        pending = state.pending_call_id
        if state.runner is not None:
            state.runner.interrupt()
            state.runner.drain()
        if pending:
            state.cancelled_call_ids.add(pending)
        state.pending_call_id = None
        state.input_transcript = ""
        state.pre_authorization_audio_bytes = 0
        state.activity_active = False
        state.awaiting_authorized_response = False
        return {
            "interrupted": True,
            "pending_call_cancelled": bool(pending),
            "method": "send_client_content_turn_complete",
        }
    def mark_user_interrupt(self, provider_session_reference: str):
        state = self._state(provider_session_reference)
        state.interrupt_requested = True

    def close_session(self, provider_session_reference: str) -> dict[str, Any]:
        state = self._state(provider_session_reference)
        try:
            if state.runner is not None:
                state.runner.close()
        finally:
            state.runner = None
            state.closed = True
            with self._lock:
                self._sessions.pop(provider_session_reference, None)
        return {"closed": True}


class GeminiLiveVoiceAdapter(ModelAdapter):
    provider = "google"
    supported_modalities = frozenset({"text", "audio"})

    def __init__(
        self,
        config: dict[str, Any],
        secrets: SecretResolver,
        *,
        transport: GeminiLiveVoiceTransport | None = None,
    ):
        self._config = dict(config)
        self._secrets = secrets
        self.model_id = str(config["model_id"])
        self._secret_refs = list(config.get("secret_refs", []))
        self.transport_verified = bool(
            config.get("transport_verified", False) or transport is not None
        )
        self._transport = transport
        if self._transport is None and self.transport_verified:
            self._transport = GeminiLiveVoiceTransport(
                secrets=secrets,
                secret_refs=self._secret_refs,
                model=self.model_id,
                connect_timeout=float(config.get("connect_timeout_seconds", 30)),
                turn_timeout=float(config.get("turn_timeout_seconds", 45)),
            )
    def health(self):
        secret_status = self._secrets.status(self._secret_refs)
        return {
            "provider": self.provider,
            "model": self.model_id,
            "configured": bool(self._secret_refs) and all(secret_status.values()),
            "enabled": bool(self._config.get("enabled", True)),
            "operation": "realtime_voicechat",
            "supports_streaming": True,
            "supports_tools": False,
            "function_behavior": "SPARKLE_OWNED_AUTHORIZATION",
            "transport_verified": self.transport_verified,
            "provider_input_rate": GEMINI_INPUT_RATE,
            "provider_output_rate": GEMINI_OUTPUT_RATE,
        }

    def _require_transport(self):
        if self._transport is None or not self.transport_verified:
            raise ModelError(
                "Gemini Live transport is not verified/configured",
                retryable=False,
                category="external_dependency",
            )
        return self._transport

    def open_session(self, session):
        return self._require_transport().open_session(session)

    def send_audio(self, provider_session_reference, frame):
        return self._require_transport().send_audio(
            provider_session_reference, frame
        )

    def validate_pending_call(self, provider_session_reference):
        return self._require_transport().validate_pending_call(
            provider_session_reference
        )
    def respond_text(self, provider_session_reference, text):
        return self._require_transport().respond_text(
            provider_session_reference, text
        )

    def interrupt(self, provider_session_reference):
        return self._require_transport().interrupt(provider_session_reference)

    def mark_user_interrupt(self, provider_session_reference):
        return self._require_transport().mark_user_interrupt(provider_session_reference)

    def close_session(self, provider_session_reference):
        return self._require_transport().close_session(
            provider_session_reference
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise ModelError(
            "Gemini Live voice uses realtime sessions, not chat completion",
            retryable=False,
            category="unsupported_operation",
        )
