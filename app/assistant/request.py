from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantRequest:
    """A request sent to the business assistant."""

    business_id: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string.")
