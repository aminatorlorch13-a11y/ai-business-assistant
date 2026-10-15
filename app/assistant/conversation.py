from dataclasses import dataclass
from enum import Enum




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
    """Immutable conversational history, optionally bounded for working context."""

    business_id: str
    turns: tuple[ConversationTurn, ...] = ()
    max_turns: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.turns, tuple):
            raise TypeError("turns must be a tuple.")

        if self.max_turns is not None and (
            not isinstance(self.max_turns, int)
            or isinstance(self.max_turns, bool)
            or self.max_turns <= 0
        ):
            raise ValueError("max_turns must be a positive integer or None.")

        for turn in self.turns:
            if not isinstance(turn, ConversationTurn):
                raise TypeError("turns must contain ConversationTurn objects.")

            if turn.business_id != self.business_id:
                raise ValueError(
                    "Conversation turn does not belong to this business."
                )

        if self.max_turns is not None and len(self.turns) > self.max_turns:
            raise ValueError(
                "Conversation history cannot contain more than max_turns entries."
            )

    def append(self, turn: ConversationTurn) -> "ConversationHistory":
        """Return a new history containing the supplied turn."""

        if not isinstance(turn, ConversationTurn):
            raise TypeError("turn must be a ConversationTurn.")

        if turn.business_id != self.business_id:
            raise ValueError(
                "Conversation turn does not belong to this business."
            )

        updated_turns = self.turns + (turn,)

        if self.max_turns is not None and len(updated_turns) > self.max_turns:
            updated_turns = updated_turns[-self.max_turns :]

        return ConversationHistory(
            business_id=self.business_id,
            turns=updated_turns,
            max_turns=self.max_turns,
        )

    @property
    def is_empty(self) -> bool:
        return not self.turns
