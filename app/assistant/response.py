from dataclasses import dataclass
from app.assistant.speech_direction import SpeechDirection


@dataclass(frozen=True)
class AssistantResponse:
    """A response produced by the business assistant."""

    business_id: str
    assistant_name: str
    message: str
    should_speak: bool = True
    speech_direction: SpeechDirection | None = None

    def __post_init__(self) -> None:
        if self.speech_direction is not None and not isinstance(
            self.speech_direction, SpeechDirection
        ):
            raise TypeError('speech_direction must be SpeechDirection or None.')
        fields = {
            "business_id": self.business_id,
            "assistant_name": self.assistant_name,
            "message": self.message,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")
