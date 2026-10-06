"""Compatibility entry point. New code imports ConversationService from application.conversation."""
from .application.conversation import ConversationService

__all__ = ["ConversationService"]
