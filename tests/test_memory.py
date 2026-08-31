import pytest

from app.models.memory import Memory


def test_memory_accepts_valid_data():
    memory = Memory(
        memory_id="memory-001",
        business_id="business-001",
        content="Customers prefer email receipts.",
        memory_type="customer_preference",
        importance=4,
    )

    assert memory.memory_id == "memory-001"
    assert memory.business_id == "business-001"
    assert memory.content == "Customers prefer email receipts."
    assert memory.memory_type == "customer_preference"
    assert memory.importance == 4


def test_memory_rejects_invalid_type():
    with pytest.raises(ValueError):
        Memory(
            memory_id="memory-001",
            business_id="business-001",
            content="Test",
            memory_type="random_type",
            importance=3,
        )


def test_memory_rejects_invalid_importance():
    with pytest.raises(ValueError):
        Memory(
            memory_id="memory-001",
            business_id="business-001",
            content="Test",
            memory_type="business_rule",
            importance=6,
        )


def test_memory_rejects_empty_content():
    with pytest.raises(ValueError):
        Memory(
            memory_id="memory-001",
            business_id="business-001",
            content="",
            memory_type="business_rule",
            importance=3,
        )
