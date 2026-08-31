from dataclasses import dataclass


@dataclass(frozen=True)
class AssistantResponse:
    """A response produced by the business assistant."""

    business_id: str
    assistant_name: str
    message: str
    should_speak: bool = True

    def __post_init__(self) -> None:
        fields = {
            "business_id": self.business_id,
            "assistant_name": self.assistant_name,
            "message": self.message,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")
