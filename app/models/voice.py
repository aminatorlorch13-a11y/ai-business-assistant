from dataclasses import dataclass


SUPPORTED_VOICES = {
    "female",
    "male",
}


@dataclass(frozen=True)
class VoiceConfiguration:
    """Configuration for the voice used by a business assistant."""

    voice: str
    speed: float = 1.0

    def __post_init__(self) -> None:
        if self.voice not in SUPPORTED_VOICES:
            raise ValueError(
                f"voice must be one of: "
                f"{', '.join(sorted(SUPPORTED_VOICES))}."
            )

        if not isinstance(self.speed, (int, float)):
            raise ValueError("speed must be a number.")

        if self.speed <= 0:
            raise ValueError("speed must be greater than zero.")
