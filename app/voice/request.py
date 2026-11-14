from dataclasses import dataclass
from typing import ClassVar
import math

from app.models.voice import SUPPORTED_VOICES


@dataclass(frozen=True)
class VocalizationEvent:
    """A non-verbal vocal event positioned inside spoken text."""

    kind: str
    position: int
    intensity: str = "moderate"

    SUPPORTED_KINDS: ClassVar[frozenset[str]] = frozenset({
        "laugh",
        "chuckle",
        "sigh",
        "breath",
    })

    SUPPORTED_INTENSITIES: ClassVar[frozenset[str]] = frozenset({
        "mild",
        "moderate",
        "strong",
    })

    def __post_init__(self) -> None:
        if self.kind not in self.SUPPORTED_KINDS:
            raise ValueError(
                f"Unsupported vocalization: {self.kind!r}."
            )

        if (
            isinstance(self.position, bool)
            or not isinstance(self.position, int)
            or self.position < 0
        ):
            raise ValueError(
                "Vocalization position must be a non-negative integer."
            )

        if self.intensity not in self.SUPPORTED_INTENSITIES:
            raise ValueError(
                f"Unsupported vocalization intensity: {self.intensity!r}."
            )


@dataclass(frozen=True)
class SpeechRequest:
    """Validated, provider-neutral request for expressive speech."""

    text: str
    voice: str
    speed: float = 1.0

    emotion: str = "neutral"
    delivery: str = "normal"
    pitch: float | None = None
    vocalizations: tuple[VocalizationEvent, ...] = ()

    SUPPORTED_EMOTIONS: ClassVar[frozenset[str]] = frozenset({
        "neutral",
        "amused",
        "excited",
        "empathetic",
        "sad",
        "curious",
        "serious",
        "soothing",
    })

    SUPPORTED_DELIVERIES: ClassVar[frozenset[str]] = frozenset({
        "normal",
        "soft",
        "whisper",
    })

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

        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
        ):
            raise ValueError("speed must be a number.")

        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError(
                "speed must be a finite number greater than zero."
            )

        if self.emotion not in self.SUPPORTED_EMOTIONS:
            raise ValueError(
                f"Unsupported emotion: {self.emotion!r}."
            )

        if self.delivery not in self.SUPPORTED_DELIVERIES:
            raise ValueError(
                f"Unsupported delivery: {self.delivery!r}."
            )

        if self.pitch is not None:
            if (
                isinstance(self.pitch, bool)
                or not isinstance(self.pitch, (int, float))
            ):
                raise ValueError("pitch must be a number when provided.")

            if not math.isfinite(self.pitch) or not -6 <= self.pitch <= 6:
                raise ValueError(
                    "pitch must be between -6 and +6 semitones."
                )

        if not isinstance(self.vocalizations, tuple):
            raise ValueError("vocalizations must be a tuple.")

        previous_position = -1

        for event in self.vocalizations:
            if not isinstance(event, VocalizationEvent):
                raise TypeError(
                    "vocalizations must contain VocalizationEvent instances."
                )

            if event.position > len(self.text):
                raise ValueError(
                    "A vocalization position cannot exceed the text length."
                )

            if event.position < previous_position:
                raise ValueError(
                    "Vocalization events must be ordered by text position."
                )

            previous_position = event.position

    @property
    def has_expressive_features(self) -> bool:
        """Whether this request asks for anything beyond default speech."""
        return (
            self.emotion != "neutral"
            or self.delivery != "normal"
            or self.pitch is not None
            or bool(self.vocalizations)
        )
