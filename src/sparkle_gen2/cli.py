"""Compatibility entry point for the SPARKLE CLI."""
from .interfaces.cli import *
from .interfaces.cli import entrypoint

__all__ = ["entrypoint"]
