"""Reusable HTTP transport primitives.

Route handlers should use these helpers rather than owning serialization,
request-size enforcement, authentication parsing, or static-file policy.
"""
from __future__ import annotations

import json
import math
import re
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class JsonResponder:
    SECURITY_HEADERS = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'"
        ),
    }

    @classmethod
    def send(cls, handler: Any, status: int, value: Any, headers: dict[str, str] | None = None):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in cls.SECURITY_HEADERS.items():
            handler.send_header(key, value)
        for key, value in (headers or {}).items():
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)


class JsonRequest:
    @staticmethod
    def check_origin(handler: Any) -> None:
        origin = handler.headers.get('Origin')
        if not origin:
            return
        import ssl
        scheme = 'https' if isinstance(handler.connection, ssl.SSLSocket) else 'http'
        parsed = urlsplit(origin)
        if parsed.scheme != scheme or parsed.netloc.lower() != handler.headers.get('Host', '').lower() or parsed.path or parsed.query or parsed.fragment:
            raise PermissionError('cross_origin_request_denied')

    @staticmethod
    def _line(handler: Any, limit: int = 8192) -> bytes:
        line = handler.rfile.readline(limit + 1)
        if not line or len(line) > limit or not line.endswith(b"\r\n"):
            raise ValueError("invalid_chunked_body")
        return line

    @staticmethod
    def read(handler: Any, max_bytes: int = 1_000_000) -> dict[str, Any]:
        transfer_encoding = handler.headers.get("Transfer-Encoding", "").lower()
        content_length = handler.headers.get("Content-Length")
        get_all = getattr(handler.headers, "get_all", lambda key: [handler.headers[key]] if key in handler.headers else [])
        if len(get_all("Content-Length") or []) > 1 or len(get_all("Transfer-Encoding") or []) > 1:
            raise ValueError("ambiguous_request_framing")
        if transfer_encoding and (transfer_encoding != "chunked" or content_length is not None):
            raise ValueError("ambiguous_request_framing")
        content_type = handler.headers.get("Content-Type", "application/json").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("json_content_type_required")
        if transfer_encoding == "chunked":
            chunks: list[bytes] = []
            total = 0
            while True:
                line = JsonRequest._line(handler)
                token = line[:-2].split(b";", 1)[0]
                if not re.fullmatch(rb"[0-9a-fA-F]{1,16}", token):
                    raise ValueError("invalid_chunk_size")
                size = int(token, 16)
                if size == 0:
                    trailer_bytes = 0
                    while True:
                        trailer = JsonRequest._line(handler)
                        trailer_bytes += len(trailer)
                        if trailer_bytes > 16384:
                            raise ValueError("chunk_trailers_too_large")
                        if trailer == b"\r\n":
                            break
                    break
                total += size
                if total > max_bytes or len(chunks) >= 4096:
                    raise ValueError("request_too_large")
                chunk = handler.rfile.read(size)
                if len(chunk) != size:
                    raise ValueError("incomplete_chunk")
                if handler.rfile.read(2) != b"\r\n":
                    raise ValueError("invalid_chunk_ending")
                chunks.append(chunk)
            raw = b"".join(chunks)
        else:
            if content_length is not None and not re.fullmatch(r"[0-9]{1,16}", content_length):
                raise ValueError("invalid_content_length")
            try:
                size = int(content_length or "0")
            except ValueError as exc:
                raise ValueError("invalid_content_length") from exc
            if size < 0 or size > max_bytes:
                raise ValueError("request_too_large")
            raw = handler.rfile.read(size) if size else b""
            if len(raw) != size:
                raise ValueError("incomplete_request_body")

        try:
            value = json.loads(raw.decode("utf-8") if raw else "{}")
        except (UnicodeError, ValueError, RecursionError):
            raise ValueError("invalid_json_body") from None
        if not isinstance(value, dict):
            raise ValueError("json_object_required")
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if count > 10000 or depth > 24:
                raise ValueError("json_structure_too_large")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("finite_json_numbers_required")
            if isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        return value

    @staticmethod
    def validate_fields(value: dict[str, Any]) -> None:
        """Reject malformed public fields before any service can mutate state."""
        strings = {
            'agent_id', 'audio_base64', 'capability', 'channel_reference', 'classification',
            'client', 'code', 'conversation_session_id', 'data_base64', 'deadline',
            'description', 'error', 'goal_id', 'kind', 'message_id', 'mime_type',
            'modality', 'mode', 'model_id', 'name', 'objective', 'os', 'permission',
            'preferred_device_id', 'prompt', 'record_id', 'record_type', 'session_id',
            'status', 'subject', 'target_device_id', 'text', 'title',
        }
        nullable = {'channel_reference', 'conversation_session_id', 'deadline', 'error',
                    'mime_type', 'model_id', 'preferred_device_id', 'session_id', 'target_device_id'}
        for field, item in value.items():
            if field in strings and not isinstance(item, str) and not (field in nullable and item is None):
                raise ValueError('invalid_field_type:' + field)
            if field in {'final', 'persist_transcript', 'supported'} and type(item) is not bool:
                raise ValueError('invalid_field_type:' + field)
            if field in {'priority', 'sequence', 'max_iterations'} and type(item) is not int:
                raise ValueError('invalid_field_type:' + field)
            if field == 'time_budget_seconds' and (type(item) not in (int, float) or not math.isfinite(item) or item <= 0):
                raise ValueError('invalid_field_type:' + field)
            if field == 'metadata' and not isinstance(item, dict):
                raise ValueError('invalid_field_type:metadata')
            if field in {'capabilities', 'units', 'success_criteria'}:
                if not isinstance(item, list) or len(item) > 100 or any(not isinstance(v, str) for v in item):
                    raise ValueError('invalid_field_type:' + field)


class DeviceAuthentication:
    @staticmethod
    def token(handler: Any) -> str:
        auth = handler.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        raw = handler.headers.get("Cookie", "")
        if raw:
            cookie = SimpleCookie()
            cookie.load(raw)
            item = cookie.get("sparkle_device")
            if item and item.value:
                return item.value
        raise PermissionError("authentication_required")


class StaticFileService:
    MIME_TYPES = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ttf": "font/ttf",
    }

    def __init__(self, root: Path):
        self.root = root.resolve()

    def serve(self, handler: Any, path: str) -> bool:
        name = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        target = (self.root / name).resolve()
        if self.root not in target.parents or not target.is_file():
            return False
        raw = target.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", self.MIME_TYPES.get(
            target.suffix, "application/octet-stream"
        ))
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        handler.send_header(
            "Cache-Control",
            "no-cache" if target.name == "index.html" or target.suffix in {".js", ".css"}
            else "public, max-age=300",
        )
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
        return True
