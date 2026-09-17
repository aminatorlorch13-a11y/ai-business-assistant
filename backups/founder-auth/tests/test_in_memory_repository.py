import pytest
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

def test_repository_rejects_non_memory_objects():
    repository = InMemoryMemoryRepository()

    with pytest.raises(TypeError, match="Memory"):
        repository.save(object())


@pytest.mark.parametrize(
    "memory_id",
    [
        "",
        "   ",
        123,
        [],
        {},
    ],
)
def test_repository_rejects_invalid_memory_id(memory_id):
    repository = InMemoryMemoryRepository()

    with pytest.raises(ValueError, match="identifier"):
        repository.get(memory_id)


def test_repository_rejects_invalid_business_id():
    repository = InMemoryMemoryRepository()

    with pytest.raises(ValueError, match="identifier"):
        repository.list_for_business("")


def test_repository_rejects_overlong_identifier():
    repository = InMemoryMemoryRepository()

    with pytest.raises(ValueError, match="maximum allowed length"):
        repository.get("x" * 129)


def test_repository_preserves_memory_immutability():
    repository = InMemoryMemoryRepository()

    memory = Memory(
        memory_id="memory-001",
        business_id="business-001",
        content="Customers prefer email receipts.",
        memory_type="customer_preference",
        importance=5,
    )

    stored = repository.save(memory)

    assert stored is memory
    assert repository.get("memory-001") is memory


def test_repository_does_not_expose_other_business_memory():
    repository = InMemoryMemoryRepository()

    first = Memory(
        memory_id="memory-001",
        business_id="business-001",
        content="Business one memory.",
        memory_type="business_rule",
        importance=5,
    )

    second = Memory(
        memory_id="memory-002",
        business_id="business-002",
        content="Business two memory.",
        memory_type="business_rule",
        importance=5,
    )

    repository.save(first)
    repository.save(second)

    result = repository.list_for_business("business-001")

    assert result == [first]
    assert second not in result
