from app.memory.repository import MemoryRepository
from app.models.memory import Memory


class MemoryService:
    """Application service for managing business memories."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def save(self, memory: Memory) -> Memory:
        """Save a business memory."""
        return self._repository.save(memory)

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        return self._repository.get(memory_id)

    def list_for_business(self, business_id: str) -> list[Memory]:
        """Retrieve all memories belonging to a business."""
        return self._repository.list_for_business(business_id)

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        return self._repository.delete(memory_id)
