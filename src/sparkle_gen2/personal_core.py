"""Compatibility entry point for Personal Core HTTP server."""
from .interfaces.http_server import *
from .interfaces.http_server import PersonalCore, build_server, main, entrypoint

__all__ = ["PersonalCore", "build_server", "main", "entrypoint"]
