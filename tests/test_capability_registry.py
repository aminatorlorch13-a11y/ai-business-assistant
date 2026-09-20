import pytest

from app.assistant.capability import Capability
from app.assistant.capability_registry import build_capability_router
from app.assistant.capability_router import CapabilityRouter
from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.memory.scoped_service import ScopedMemoryService


def make_service() -> ScopedMemoryService:
    return ScopedMemoryService(InMemoryMemoryRepository())


def test_production_registry_registers_only_real_memory_operations():
    router = build_capability_router(make_service())

    assert isinstance(router, CapabilityRouter)

    assert router.supports(Capability.MEMORY) is True
    assert router.supports_operation(Capability.MEMORY, "save") is True
    assert router.supports_operation(Capability.MEMORY, "get") is True
    assert router.supports_operation(Capability.MEMORY, "list") is True
    assert router.supports_operation(Capability.MEMORY, "delete") is True

    assert router.supports(Capability.RESEARCH) is False
    assert router.supports(Capability.CALENDAR) is False


def test_registry_rejects_invalid_memory_service():
    with pytest.raises(TypeError, match="ScopedMemoryService"):
        build_capability_router(object())


def test_registry_has_no_unregistered_memory_operation():
    router = build_capability_router(make_service())

    assert router.supports_operation(
        Capability.MEMORY,
        "remember_everything",
    ) is False
