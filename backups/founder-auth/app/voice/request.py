from dataclasses import dataclass
import math

from app.models.voice import SUPPORTED_VOICES


@dataclass(frozen=True)
class SpeechRequest:
    """Validated request to convert assistant text into spoken audio."""

    text: str
    voice: str
    speed: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string.")

        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice must be a non-empty string.")

        if self.voice not in SUPPORTED_VOICES:
            raise ValueError(
                "voice must be one of: "
                f"{', '.join(sorted(SUPPORTED_VOICES))}."
            )

        if isinstance(self.speed, bool) or not isinstance(
            self.speed, (int, float)
        ):
            raise ValueError("speed must be a number.")

        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError(
                "speed must be a finite number greater than zero."
            )
