from dataclasses import dataclass


SUPPORTED_VOICES = {"female", "male"}


@dataclass(frozen=True)
class Business:
    """Represents a business using the Business Assistant platform."""

    business_id: str
    name: str
    owner_name: str
    assistant_name: str
    assistant_voice: str

    def __post_init__(self) -> None:
        fields = {
            "business_id": self.business_id,
            "name": self.name,
            "owner_name": self.owner_name,
            "assistant_name": self.assistant_name,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if self.assistant_voice not in SUPPORTED_VOICES:
            raise ValueError(
                f"assistant_voice must be one of: "
                f"{', '.join(sorted(SUPPORTED_VOICES))}."
            )
