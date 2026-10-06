from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

VOICE_PROVIDER_SETTING = "VOICE_PROVIDER"
VOICE_PROVIDER_ALIASES = {
    "nvidia": "nvidia-nemotron-voicechat",
    "gemini": "google-gemini-3.8-live",
}


def normalize_voice_provider(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized not in VOICE_PROVIDER_ALIASES:
        raise ValueError("voice_provider must be one of: gemini, nvidia")
    return normalized


@runtime_checkable
class VoiceProvider(Protocol):
    def open_session(self, session: dict[str, Any]) -> str: ...
    def send_audio(self, provider_session_reference: str, frame: Any) -> dict[str, Any]: ...
    def respond_text(self, provider_session_reference: str, text: str) -> dict[str, Any]: ...
    def interrupt(self, provider_session_reference: str) -> dict[str, Any]: ...
    def close_session(self, provider_session_reference: str) -> dict[str, Any]: ...
