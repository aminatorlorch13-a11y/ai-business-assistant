from app.models.memory import Memory


class InMemoryMemoryRepository:
    """
    Process-local repository implementation for business memory.

    Repository invariants:
    - Only Memory objects may be stored.
    - Stored values are immutable Memory instances.
    - Memory IDs are unique storage keys.
    - Missing records return None/False rather than raising.
    - Invalid inputs fail explicitly.
    """

    MAX_ID_LENGTH = 128

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def save(self, memory: Memory) -> Memory:
        """Store one validated Memory object."""
        if not isinstance(memory, Memory):
            raise TypeError("memory must be a Memory.")

        self._validate_id(memory.memory_id)

        self._memories[memory.memory_id] = memory
        return memory

    def get(self, memory_id: str) -> Memory | None:
        """Return a memory by ID, or None when it does not exist."""
        self._validate_id(memory_id)
        return self._memories.get(memory_id)

    def list_for_business(self, business_id: str) -> list[Memory]:
        """Return only memories belonging to the requested business."""
        self._validate_id(business_id)

        return [
            memory
            for memory in self._memories.values()
            if memory.business_id == business_id
        ]

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID and report whether it existed."""
        self._validate_id(memory_id)

        if memory_id not in self._memories:
            return False

        del self._memories[memory_id]
        return True

    @classmethod
    def _validate_id(cls, value: object) -> None:
        """Validate repository identifiers."""
        if not isinstance(value, str):
            raise ValueError("identifier must be a non-empty string.")

        if not value.strip():
            raise ValueError("identifier must be a non-empty string.")

        if len(value) > cls.MAX_ID_LENGTH:
            raise ValueError(
                "identifier exceeds the maximum allowed length."
            )
