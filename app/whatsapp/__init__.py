"""WhatsApp channel boundary.

This package intentionally avoids eager imports of channel services and
identity resolvers.  Persistence modules import WhatsApp data models, while
identity/service modules import persistence.  Keeping package initialization
lightweight prevents circular imports during module loading.
"""

__all__ = [
    "models",
    "security",
    "provider",
    "identity",
    "message_adapter",
    "service",
]
