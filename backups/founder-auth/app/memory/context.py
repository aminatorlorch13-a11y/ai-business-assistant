from dataclasses import dataclass

from app.memory.scoped_service import ScopedMemoryService
from app.models.memory import Memory


@dataclass(frozen=True)
class MemoryContext:
    """Controlled memory context supplied to the assistant."""

    business_id: str
    memories: tuple[Memory, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.memories, tuple):
            raise TypeError("memories must be a tuple.")

        for memory in self.memories:
            if not isinstance(memory, Memory):
                raise TypeError("memories must contain only Memory objects.")

            if memory.business_id != self.business_id:
                raise ValueError(
                    "MemoryContext cannot contain memory from another business."
                )

    @property
    def is_empty(self) -> bool:
        """Return whether the context contains no memories."""
        return not self.memories

    def as_text(self) -> str:
        """Return a controlled textual representation for an AI provider."""
        if self.is_empty:
            return ""

        return "\n".join(
            f"- [{memory.memory_type}] {memory.content}"
            for memory in self.memories
        )


class MemoryContextBuilder:
    """Builds a bounded, business-scoped memory context."""

    DEFAULT_MAX_MEMORIES = 10

    def __init__(
        self,
        memory_service: ScopedMemoryService,
        max_memories: int = DEFAULT_MAX_MEMORIES,
    ) -> None:
        if not isinstance(memory_service, ScopedMemoryService):
            raise TypeError(
                "memory_service must be a ScopedMemoryService."
            )

        if not isinstance(max_memories, int):
            raise TypeError("max_memories must be an integer.")

        if max_memories < 1:
            raise ValueError("max_memories must be at least 1.")

        self._memory_service = memory_service
        self._max_memories = max_memories

    def build(self, business_id: str) -> MemoryContext:
        """Build a bounded context containing only this business's memories."""
        self._validate_business_id(business_id)

        memories = self._memory_service.list_for_business(business_id)

        ordered_memories = sorted(
            memories,
            key=lambda memory: (-memory.importance, memory.memory_id),
        )

        selected = tuple(ordered_memories[: self._max_memories])

        return MemoryContext(
            business_id=business_id,
            memories=selected,
        )

    @staticmethod
    def _validate_business_id(business_id: object) -> None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")
