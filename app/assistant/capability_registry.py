from __future__ import annotations

from app.assistant.capability import Capability
from app.assistant.capability_handlers import ForgeCapabilityHandlers
from app.forge.job_store import ForgeJobStore
from app.assistant.capability_handlers import MemoryCapabilityHandlers
from app.assistant.capability_router import CapabilityRouter
from app.memory.scoped_service import ScopedMemoryService
from app.assistant.gmail_capability_handlers import GmailCapabilityHandlers


def build_capability_router(
    memory_service: ScopedMemoryService,
    forge_job_store: ForgeJobStore | None = None,
    gmail_integration_service=None,
) -> CapabilityRouter:
    """Build the closed-world production capability registry."""

    handlers = MemoryCapabilityHandlers(memory_service)

    registered_handlers = {
            Capability.MEMORY: {
                "save": handlers.save,
                "get": handlers.get,
                "list": handlers.list,
                "delete": handlers.delete,
            },
        }
    if forge_job_store is not None:
        forge = ForgeCapabilityHandlers(forge_job_store)
        registered_handlers[Capability.FORGE] = {
            "submit_job": forge.submit_job,
            "get_job": forge.get_job,
            "list_jobs": forge.list_jobs,
        }
    if gmail_integration_service is not None:
        gmail = GmailCapabilityHandlers(gmail_integration_service)
        registered_handlers[Capability.COMMUNICATION] = {
            "gmail_search": gmail.search,
            "gmail_read": gmail.read,
        }
    return CapabilityRouter(
        handlers=registered_handlers
    )
