from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantMessage:
    """A message received by the business assistant."""

    business_id: str
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("content must be a non-empty string.")
