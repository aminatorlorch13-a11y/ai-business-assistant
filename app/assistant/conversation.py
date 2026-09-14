from dataclasses import dataclass
from enum import Enum


DEFAULT_MAX_CONVERSATION_TURNS = 24


class ConversationRole(Enum):
    """Roles represented in the assistant's conversational context."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ConversationTurn:
    """One immutable business-scoped conversational turn."""

    business_id: str
    role: ConversationRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.role, ConversationRole):
            raise TypeError("role must be a ConversationRole.")

        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string.")


@dataclass(frozen=True)
class ConversationHistory:
    """Bounded, immutable conversational history for one business."""

    business_id: str
    turns: tuple[ConversationTurn, ...] = ()
    max_turns: int = DEFAULT_MAX_CONVERSATION_TURNS

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.turns, tuple):
            raise TypeError("turns must be a tuple.")

        if not isinstance(self.max_turns, int) or self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer.")

        for turn in self.turns:
            if not isinstance(turn, ConversationTurn):
                raise TypeError("turns must contain ConversationTurn objects.")

            if turn.business_id != self.business_id:
                raise ValueError(
                    "Conversation turn does not belong to this business."
                )

        if len(self.turns) > self.max_turns:
            raise ValueError(
                "Conversation history cannot contain more than max_turns entries."
            )

    def append(self, turn: ConversationTurn) -> "ConversationHistory":
        """Return a new bounded history containing the supplied turn."""

        if not isinstance(turn, ConversationTurn):
            raise TypeError("turn must be a ConversationTurn.")

        if turn.business_id != self.business_id:
            raise ValueError(
                "Conversation turn does not belong to this business."
            )

        updated_turns = self.turns + (turn,)

        if len(updated_turns) > self.max_turns:
            updated_turns = updated_turns[-self.max_turns :]

        return ConversationHistory(
            business_id=self.business_id,
            turns=updated_turns,
            max_turns=self.max_turns,
        )

    @property
    def is_empty(self) -> bool:
        return not self.turns
