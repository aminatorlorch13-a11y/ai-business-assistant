from app.models.memory import Memory


class InMemoryMemoryRepository:
    """Temporary process-local repository used by the application tests."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def save(self, memory: Memory) -> Memory:
        self._memories[memory.memory_id] = memory
        return memory

    def get(self, memory_id: str) -> Memory | None:
        return self._memories.get(memory_id)

    def list_for_business(self, business_id: str) -> list[Memory]:
        return [
            memory
            for memory in self._memories.values()
            if memory.business_id == business_id
        ]

    def delete(self, memory_id: str) -> bool:
        if memory_id not in self._memories:
            return False

        del self._memories[memory_id]
        return True
