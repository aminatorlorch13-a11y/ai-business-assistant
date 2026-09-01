from app.memory.repository import MemoryRepository
from app.models.memory import Memory


class ScopedMemoryService:
    """Provides business-scoped access to persistent assistant memory."""

    MAX_BUSINESS_ID_LENGTH = 128

    def __init__(self, repository: MemoryRepository) -> None:
        if repository is None:
            raise TypeError("repository must be provided.")

        self._repository = repository

    def save(self, memory: Memory) -> Memory:
        """Save memory after validating its business identity."""
        if not isinstance(memory, Memory):
            raise TypeError("memory must be a Memory.")

        self._validate_business_id(memory.business_id)

        return self._repository.save(memory)

    def get(self, business_id: str, memory_id: str) -> Memory | None:
        """Retrieve a memory only when it belongs to the requested business."""
        self._validate_business_id(business_id)
        self._validate_memory_id(memory_id)

        memory = self._repository.get(memory_id)

        if memory is None:
            return None

        if memory.business_id != business_id:
            return None

        return memory

    def list_for_business(self, business_id: str) -> list[Memory]:
        """Return only memories belonging to the requested business."""
        self._validate_business_id(business_id)

        memories = self._repository.list_for_business(business_id)

        for memory in memories:
            if memory.business_id != business_id:
                raise ValueError(
                    "Memory repository returned memory for another business."
                )

        return memories

    def delete(self, business_id: str, memory_id: str) -> bool:
        """Delete a memory only when it belongs to the requested business."""
        self._validate_business_id(business_id)
        self._validate_memory_id(memory_id)

        memory = self._repository.get(memory_id)

        if memory is None:
            return False

        if memory.business_id != business_id:
            return False

        return self._repository.delete(memory_id)

    @classmethod
    def _validate_business_id(cls, business_id: object) -> None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if len(business_id) > cls.MAX_BUSINESS_ID_LENGTH:
            raise ValueError(
                "business_id exceeds the maximum allowed length."
            )

    @staticmethod
    def _validate_memory_id(memory_id: object) -> None:
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise ValueError("memory_id must be a non-empty string.")
