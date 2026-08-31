from typing import Protocol

from app.models.memory import Memory


class MemoryRepository(Protocol):
    """Defines the storage operations required for business memory."""

    def save(self, memory: Memory) -> Memory:
        """Store a memory and return the stored memory."""
        ...

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by its ID."""
        ...

    def list_for_business(self, business_id: str) -> list[Memory]:
        """Return all memories belonging to a business."""
        ...

    def delete(self, memory_id: str) -> bool:
        """Delete a memory and report whether it existed."""
        ...
