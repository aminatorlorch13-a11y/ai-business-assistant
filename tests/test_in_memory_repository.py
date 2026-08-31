from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.models.memory import Memory


def make_memory(memory_id: str, business_id: str) -> Memory:
    return Memory(
        memory_id=memory_id,
        business_id=business_id,
        content="Customers prefer email receipts.",
        memory_type="customer_preference",
        importance=4,
    )


def test_repository_saves_and_gets_memory():
    repository = InMemoryMemoryRepository()
    memory = make_memory("memory-001", "business-001")

    repository.save(memory)

    assert repository.get("memory-001") == memory


def test_repository_returns_none_for_unknown_memory():
    repository = InMemoryMemoryRepository()

    assert repository.get("does-not-exist") is None


def test_repository_lists_only_memories_for_requested_business():
    repository = InMemoryMemoryRepository()

    first = make_memory("memory-001", "business-001")
    second = make_memory("memory-002", "business-002")

    repository.save(first)
    repository.save(second)

    memories = repository.list_for_business("business-001")

    assert memories == [first]


def test_repository_deletes_memory():
    repository = InMemoryMemoryRepository()
    memory = make_memory("memory-001", "business-001")

    repository.save(memory)

    assert repository.delete("memory-001") is True
    assert repository.get("memory-001") is None


def test_repository_reports_missing_memory_on_delete():
    repository = InMemoryMemoryRepository()

    assert repository.delete("does-not-exist") is False
