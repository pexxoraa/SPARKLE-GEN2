"""Compatibility entry point. New code imports PersonalAgent from agents.personal."""
from .agents.personal import PersonalAgent

__all__ = ["PersonalAgent"]
