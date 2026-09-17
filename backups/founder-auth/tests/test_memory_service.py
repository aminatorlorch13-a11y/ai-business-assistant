from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.memory.service import MemoryService
from app.models.memory import Memory


def make_memory(memory_id: str, business_id: str) -> Memory:
    return Memory(
        memory_id=memory_id,
        business_id=business_id,
        content="Customers prefer email receipts.",
        memory_type="customer_preference",
        importance=4,
    )


def test_service_saves_memory():
    repository = InMemoryMemoryRepository()
    service = MemoryService(repository)
    memory = make_memory("memory-001", "business-001")

    result = service.save(memory)

    assert result == memory
    assert repository.get("memory-001") == memory


def test_service_gets_memory():
    repository = InMemoryMemoryRepository()
    service = MemoryService(repository)
    memory = make_memory("memory-001", "business-001")

    repository.save(memory)

    assert service.get("memory-001") == memory


def test_service_lists_business_memories():
    repository = InMemoryMemoryRepository()
    service = MemoryService(repository)

    first = make_memory("memory-001", "business-001")
    second = make_memory("memory-002", "business-002")

    service.save(first)
    service.save(second)

    assert service.list_for_business("business-001") == [first]


def test_service_deletes_memory():
    repository = InMemoryMemoryRepository()
    service = MemoryService(repository)
    memory = make_memory("memory-001", "business-001")

    service.save(memory)

    assert service.delete("memory-001") is True
    assert service.get("memory-001") is None
