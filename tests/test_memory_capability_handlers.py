import pytest

from app.assistant.capability import Capability
from app.assistant.capability_handlers import MemoryCapabilityHandlers
from app.assistant.execution import CapabilityExecutionRequest
from app.memory.in_memory_repository import InMemoryMemoryRepository
from app.memory.scoped_service import ScopedMemoryService
from app.models.memory import Memory


def make_handlers() -> MemoryCapabilityHandlers:
    repository = InMemoryMemoryRepository()
    service = ScopedMemoryService(repository)
    return MemoryCapabilityHandlers(service)


def make_request(
    operation: str,
    arguments: dict,
    business_id: str = "business-001",
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability=Capability.MEMORY,
        operation=operation,
        business_id=business_id,
        arguments=arguments,
        reason="Test memory capability.",
    )


def test_save_persists_memory_using_trusted_business_identity():
    handlers = make_handlers()

    result = handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-001",
                "content": "Customers prefer email receipts.",
                "memory_type": "customer_preference",
                "importance": 4,
            },
        )
    )

    assert result.success is True
    assert result.capability is Capability.MEMORY
    assert result.operation == "save"
    assert result.business_id == "business-001"
    assert isinstance(result.data, Memory)
    assert result.data.business_id == "business-001"


def test_save_rejects_business_id_in_untrusted_arguments():
    handlers = make_handlers()

    with pytest.raises(ValueError, match="Unexpected memory arguments"):
        handlers.save(
            make_request(
                "save",
                {
                    "memory_id": "memory-001",
                    "business_id": "business-999",
                    "content": "Cross-business attempt.",
                    "memory_type": "business_rule",
                    "importance": 5,
                },
            )
        )


def test_get_is_business_scoped():
    handlers = make_handlers()

    handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-001",
                "content": "Private business memory.",
                "memory_type": "business_rule",
                "importance": 5,
            },
        )
    )

    result = handlers.get(
        make_request(
            "get",
            {"memory_id": "memory-001"},
            business_id="business-999",
        )
    )

    assert result.success is True
    assert result.data is None
    assert result.business_id == "business-999"


def test_list_is_business_scoped():
    handlers = make_handlers()

    handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-001",
                "content": "Business one memory.",
                "memory_type": "business_rule",
                "importance": 5,
            },
            business_id="business-001",
        )
    )
    handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-002",
                "content": "Business two memory.",
                "memory_type": "business_rule",
                "importance": 5,
            },
            business_id="business-002",
        )
    )

    result = handlers.list(
        make_request("list", {}, business_id="business-001")
    )

    assert result.success is True
    assert result.data == (
        Memory(
            memory_id="memory-001",
            business_id="business-001",
            content="Business one memory.",
            memory_type="business_rule",
            importance=5,
        ),
    )


def test_delete_successfully_removes_memory():
    handlers = make_handlers()

    handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-001",
                "content": "Memory to delete.",
                "memory_type": "business_rule",
                "importance": 4,
            },
            business_id="business-001",
        )
    )

    result = handlers.delete(
        make_request(
            "delete",
            {"memory_id": "memory-001"},
            business_id="business-001",
        )
    )

    assert result.success is True
    assert result.data is True

    lookup = handlers.get(
        make_request(
            "get",
            {"memory_id": "memory-001"},
            business_id="business-001",
        )
    )

    assert lookup.success is True
    assert lookup.data is None


def test_delete_is_business_scoped():
    handlers = make_handlers()

    handlers.save(
        make_request(
            "save",
            {
                "memory_id": "memory-001",
                "content": "Protected memory.",
                "memory_type": "business_rule",
                "importance": 5,
            },
            business_id="business-001",
        )
    )

    result = handlers.delete(
        make_request(
            "delete",
            {"memory_id": "memory-001"},
            business_id="business-999",
        )
    )

    assert result.success is True
    assert result.data is False


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("save", {}),
        ("get", {}),
        ("delete", {}),
    ],
)
def test_memory_handlers_reject_missing_arguments(operation, arguments):
    handlers = make_handlers()

    with pytest.raises(ValueError, match="Missing required memory arguments"):
        getattr(handlers, operation)(
            make_request(operation, arguments)
        )


def test_list_rejects_unexpected_arguments():
    handlers = make_handlers()

    with pytest.raises(ValueError, match="Unexpected memory arguments"):
        handlers.list(
            make_request(
                "list",
                {"memory_id": "malicious"},
            )
        )


def test_save_rejects_wrong_capability():
    handlers = make_handlers()

    request = CapabilityExecutionRequest(
        capability=Capability.CALCULATOR,
        operation="save",
        business_id="business-001",
        arguments={},
        reason="Invalid capability.",
    )

    with pytest.raises(ValueError, match="only accept the memory capability"):
        handlers.save(request)


def test_handlers_reject_non_request():
    handlers = make_handlers()

    with pytest.raises(TypeError, match="CapabilityExecutionRequest"):
        handlers.get(object())
