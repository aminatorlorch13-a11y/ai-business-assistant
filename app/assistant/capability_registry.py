from __future__ import annotations

from app.assistant.capability import Capability
from app.assistant.capability_handlers import MemoryCapabilityHandlers
from app.assistant.capability_router import CapabilityRouter
from app.memory.scoped_service import ScopedMemoryService


def build_capability_router(
    memory_service: ScopedMemoryService,
) -> CapabilityRouter:
    """Build the closed-world production capability registry."""

    handlers = MemoryCapabilityHandlers(memory_service)

    return CapabilityRouter(
        handlers={
            Capability.MEMORY: {
                "save": handlers.save,
                "get": handlers.get,
                "list": handlers.list,
                "delete": handlers.delete,
            },
        }
    )
