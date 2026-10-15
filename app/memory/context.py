from dataclasses import dataclass
import re

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
    """Build a bounded, business-scoped, request-aware memory context."""

    DEFAULT_MAX_MEMORIES = 10
    _TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
    _IGNORED_TERMS = frozenset({
        "a", "about", "after", "again", "all", "also", "am", "an", "and",
        "any", "are", "as", "at", "be", "because", "been", "before",
        "being", "but", "by", "can", "could", "did", "do", "does", "for",
        "from", "get", "got", "had", "has", "have", "he", "her", "here",
        "him", "his", "how", "i", "if", "in", "into", "is", "it", "its",
        "just", "me", "my", "of", "on", "or", "our", "please", "she",
        "should", "so", "some", "than", "that", "the", "their", "them",
        "then", "there", "these", "they", "this", "those", "to", "up",
        "us", "was", "we", "were", "what", "when", "where", "which",
        "who", "why", "will", "with", "would", "you", "your",
    })

    def __init__(
        self,
        memory_service: ScopedMemoryService,
        max_memories: int = DEFAULT_MAX_MEMORIES,
    ) -> None:
        if not isinstance(memory_service, ScopedMemoryService):
            raise TypeError("memory_service must be a ScopedMemoryService.")
        if not isinstance(max_memories, int):
            raise TypeError("max_memories must be an integer.")
        if max_memories < 1:
            raise ValueError("max_memories must be at least 1.")

        self._memory_service = memory_service
        self._max_memories = max_memories

    def build(
        self,
        business_id: str,
        query: str | None = None,
    ) -> MemoryContext:
        """Select this business's relevant memories without changing storage."""
        self._validate_business_id(business_id)
        if query is not None and not isinstance(query, str):
            raise TypeError("query must be a string or None.")

        memories = self._memory_service.list_for_business(business_id)
        query_terms = self._terms(query or "")

        if query_terms:
            scored = [
                (
                    len(query_terms & self._terms(
                        f"{memory.memory_type} {memory.content}"
                    )),
                    memory.importance,
                    memory.memory_id,
                    memory,
                )
                for memory in memories
            ]
            # Relevance first; importance and stable ID break ties.
            # If nothing matches, preserve the established importance fallback.
            if any(score > 0 for score, _, _, _ in scored):
                ordered_memories = [
                    memory
                    for score, _, _, memory in sorted(
                        scored,
                        key=lambda item: (-item[0], -item[1], item[2]),
                    )
                ]
            else:
                ordered_memories = sorted(
                    memories,
                    key=lambda memory: (-memory.importance, memory.memory_id),
                )
        else:
            ordered_memories = sorted(
                memories,
                key=lambda memory: (-memory.importance, memory.memory_id),
            )

        return MemoryContext(
            business_id=business_id,
            memories=tuple(ordered_memories[:self._max_memories]),
        )

    @classmethod
    def _terms(cls, text: str) -> set[str]:
        return {
            term
            for term in cls._TOKEN_PATTERN.findall(text.lower())
            if term not in cls._IGNORED_TERMS and len(term) > 1
        }

    @staticmethod
    def _validate_business_id(business_id: object) -> None:
        if not isinstance(business_id, str) or not business_id.strip():
            raise ValueError("business_id must be a non-empty string.")
