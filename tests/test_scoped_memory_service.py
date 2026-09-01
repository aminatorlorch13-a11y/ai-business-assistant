import pytest

from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.memory.scoped_service import ScopedMemoryService
from app.models.memory import Memory


def make_memory(memory_id: str, business_id: str) -> Memory:
    return Memory(
        memory_id=memory_id,
        business_id=business_id,
        content="Customers prefer email receipts.",
        memory_type="customer_preference",
        importance=4,
    )


def test_scoped_service_saves_memory():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    memory = make_memory("memory-001", "business-001")

    assert service.save(memory) == memory


def test_scoped_service_gets_memory_for_owner_business():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    memory = make_memory("memory-001", "business-001")
    repository.save(memory)

    assert service.get("business-001", "memory-001") == memory


def test_scoped_service_hides_memory_from_other_business():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    memory = make_memory("memory-001", "business-001")
    repository.save(memory)

    assert service.get("business-999", "memory-001") is None


def test_scoped_service_lists_business_memories():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    first = make_memory("memory-001", "business-001")
    second = make_memory("memory-002", "business-002")

    repository.save(first)
    repository.save(second)

    assert service.list_for_business("business-001") == [first]


def test_scoped_service_cannot_delete_other_business_memory():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    memory = make_memory("memory-001", "business-001")
    repository.save(memory)

    assert service.delete("business-999", "memory-001") is False
    assert repository.get("memory-001") == memory


def test_scoped_service_deletes_owned_memory():
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)

    memory = make_memory("memory-001", "business-001")
    repository.save(memory)

    assert service.delete("business-001", "memory-001") is True
    assert repository.get("memory-001") is None


def test_scoped_service_rejects_invalid_business_id():
    service = ScopedMemoryService(InMemoryMemoryRepository())

    with pytest.raises(ValueError, match="business_id"):
        service.list_for_business("")


def test_scoped_service_rejects_invalid_memory_id():
    service = ScopedMemoryService(InMemoryMemoryRepository())

    with pytest.raises(ValueError, match="memory_id"):
        service.get("business-001", "")


def test_scoped_service_rejects_non_memory():
    service = ScopedMemoryService(InMemoryMemoryRepository())

    with pytest.raises(TypeError, match="Memory"):
        service.save(object())
