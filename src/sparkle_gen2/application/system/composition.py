"""Small composition helpers for system-level services."""
from __future__ import annotations
from typing import Any

def service_map(**services: Any) -> dict[str, Any]:
    """Return an explicit named service map for diagnostics and interfaces."""
    return dict(services)
