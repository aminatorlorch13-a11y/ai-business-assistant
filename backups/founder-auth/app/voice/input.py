from dataclasses import dataclass
from enum import Enum


class ConversationInputSource(Enum):
    """Origin of user input entering a conversation."""

    VOICE = "voice"
    TEXT = "text"


@dataclass(frozen=True)
class ConversationInput:
    """Validated user input entering the shared conversation pipeline."""

    text: str
    source: ConversationInputSource

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string.")

        if not isinstance(self.source, ConversationInputSource):
            raise TypeError(
                "source must be a ConversationInputSource."
            )
