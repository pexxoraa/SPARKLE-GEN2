"""Reusable HTTP transport primitives.

Route handlers should use these helpers rather than owning serialization,
request-size enforcement, authentication parsing, or static-file policy.
"""
from __future__ import annotations

import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


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
    def read(handler: Any, max_bytes: int = 1_000_000) -> dict[str, Any]:
        transfer_encoding = handler.headers.get("Transfer-Encoding", "").lower()
        content_length = handler.headers.get("Content-Length")

        if "chunked" in transfer_encoding:
            chunks: list[bytes] = []
            total = 0
            while True:
                line = handler.rfile.readline()
                if not line:
                    raise ValueError("invalid_chunked_body")
                try:
                    size = int(line.split(b";", 1)[0].strip(), 16)
                except ValueError as exc:
                    raise ValueError("invalid_chunk_size") from exc
                if size == 0:
                    while True:
                        trailer = handler.rfile.readline()
                        if not trailer or trailer in (b"\r\n", b"\n"):
                            break
                    break
                total += size
                if total > max_bytes:
                    raise ValueError("request_too_large")
                chunk = handler.rfile.read(size)
                if len(chunk) != size:
                    raise ValueError("incomplete_chunk")
                if handler.rfile.read(2) != b"\r\n":
                    raise ValueError("invalid_chunk_ending")
                chunks.append(chunk)
            raw = b"".join(chunks)
        else:
            try:
                size = int(content_length or "0")
            except ValueError as exc:
                raise ValueError("invalid_content_length") from exc
            if size < 0 or size > max_bytes:
                raise ValueError("request_too_large")
            raw = handler.rfile.read(size) if size else b"{}"
            if len(raw) != size:
                raise ValueError("incomplete_request_body")

        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("json_object_required")
        return value


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
