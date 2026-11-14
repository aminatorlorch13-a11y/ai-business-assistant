from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SpeechDirection:
    """Untrusted AI-proposed vocal delivery, validated at the application boundary."""

    emotion: str = "neutral"
    delivery: str = "normal"
    pitch: float | None = None

    ALLOWED_EMOTIONS = frozenset({
        "neutral", "amused", "excited", "empathetic",
        "sad", "curious", "serious", "soothing",
    })
    ALLOWED_DELIVERIES = frozenset({"normal", "soft", "whisper"})

    def __post_init__(self) -> None:
        if self.emotion not in self.ALLOWED_EMOTIONS:
            raise ValueError("Unsupported speech emotion.")
        if self.delivery not in self.ALLOWED_DELIVERIES:
            raise ValueError("Unsupported speech delivery.")
        if self.pitch is not None:
            if (
                isinstance(self.pitch, bool)
                or not isinstance(self.pitch, (int, float))
                or not math.isfinite(self.pitch)
                or not -6.0 <= self.pitch <= 6.0
            ):
                raise ValueError("Speech pitch must be between -6 and +6.")
