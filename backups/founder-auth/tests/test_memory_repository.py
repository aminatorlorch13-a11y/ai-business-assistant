from app.memory.repository import MemoryRepository


def test_memory_repository_defines_required_operations():
    required_methods = {
        "save",
        "get",
        "list_for_business",
        "delete",
    }

    for method_name in required_methods:
        assert hasattr(MemoryRepository, method_name)
