import pytest

from app.memory.context import MemoryContext, MemoryContextBuilder
from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.memory.scoped_service import ScopedMemoryService
from app.models.memory import Memory


def make_memory(
    memory_id: str,
    business_id: str,
    importance: int,
    content: str = "Customers prefer email receipts.",
) -> Memory:
    return Memory(
        memory_id=memory_id,
        business_id=business_id,
        content=content,
        memory_type="customer_preference",
        importance=importance,
    )


def make_builder(max_memories: int = 10) -> MemoryContextBuilder:
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    return MemoryContextBuilder(service, max_memories=max_memories)


def test_empty_memory_context_is_supported():
    context = MemoryContext(
        business_id="business-001",
        memories=(),
    )

    assert context.is_empty is True
    assert context.as_text() == ""


def test_memory_context_rejects_memory_from_another_business():
    memory = make_memory(
        "memory-001",
        "business-999",
        importance=5,
    )

    with pytest.raises(ValueError, match="another business"):
        MemoryContext(
            business_id="business-001",
            memories=(memory,),
        )


def test_builder_returns_only_business_memories():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    builder = MemoryContextBuilder(service)

    first = make_memory("memory-001", "business-001", 5)
    second = make_memory("memory-002", "business-002", 5)

    repository.save(first)
    repository.save(second)

    context = builder.build("business-001")

    assert context.memories == (first,)
    assert context.business_id == "business-001"


def test_builder_prioritizes_more_important_memories():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    builder = MemoryContextBuilder(service)

    low = make_memory("memory-001", "business-001", 1)
    high = make_memory("memory-002", "business-001", 5)
    medium = make_memory("memory-003", "business-001", 3)

    repository.save(low)
    repository.save(high)
    repository.save(medium)

    context = builder.build("business-001")

    assert context.memories == (high, medium, low)


def test_builder_uses_memory_id_as_deterministic_tiebreaker():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    builder = MemoryContextBuilder(service)

    second = make_memory("memory-002", "business-001", 5)
    first = make_memory("memory-001", "business-001", 5)

    repository.save(second)
    repository.save(first)

    context = builder.build("business-001")

    assert context.memories == (first, second)


def test_builder_enforces_memory_limit():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    builder = MemoryContextBuilder(service, max_memories=2)

    first = make_memory("memory-001", "business-001", 5)
    second = make_memory("memory-002", "business-001", 4)
    third = make_memory("memory-003", "business-001", 3)

    repository.save(first)
    repository.save(second)
    repository.save(third)

    context = builder.build("business-001")

    assert context.memories == (first, second)
    assert len(context.memories) == 2


def test_context_formats_memories_for_ai():
    first = make_memory(
        "memory-001",
        "business-001",
        5,
        "Customers prefer email receipts.",
    )
    second = make_memory(
        "memory-002",
        "business-001",
        4,
        "Appointments require confirmation.",
    )

    context = MemoryContext(
        business_id="business-001",
        memories=(first, second),
    )

    assert context.as_text() == (
        "- [customer_preference] Customers prefer email receipts.\n"
        "- [customer_preference] Appointments require confirmation."
    )


def test_builder_rejects_invalid_business_id():
    builder = make_builder()

    with pytest.raises(ValueError, match="business_id"):
        builder.build("")


def test_builder_rejects_invalid_memory_limit():
    service = ScopedMemoryService(InMemoryMemoryRepository())

    with pytest.raises(ValueError, match="at least 1"):
        MemoryContextBuilder(service, max_memories=0)


def test_builder_rejects_invalid_memory_limit_type():
    service = ScopedMemoryService(InMemoryMemoryRepository())

    with pytest.raises(TypeError, match="integer"):
        MemoryContextBuilder(service, max_memories="10")
