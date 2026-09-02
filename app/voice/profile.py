from dataclasses import dataclass
import math
from typing import Mapping


SUPPORTED_VOICES = frozenset({"female", "male"})


@dataclass(frozen=True)
class VoiceProfile:
    """
    Platform-neutral speech profile.

    The application selects a logical voice name such as "male" or
    "female". The speech-engine adapter resolves the provider-specific
    voice identity represented by provider_voice_id.

    Provider-specific voice IDs must never leak into the conversation
    or assistant orchestration layers.
    """

    voice: str
    provider: str | None = None
    provider_voice_id: str | None = None
    pitch: float | None = None
    speed: float = 1.0
    language: str | None = None
    region: str | None = None
    variant: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice must be a non-empty string.")

        if self.provider is not None and (
            not isinstance(self.provider, str) or not self.provider.strip()
        ):
            raise ValueError(
                "provider must be a non-empty string when provided."
            )

        if self.provider_voice_id is not None and (
            not isinstance(self.provider_voice_id, str)
            or not self.provider_voice_id.strip()
        ):
            raise ValueError(
                "provider_voice_id must be a non-empty string when provided."
            )

        if self.pitch is not None:
            if isinstance(self.pitch, bool) or not isinstance(
                self.pitch, (int, float)
            ):
                raise ValueError("pitch must be a number when provided.")

            if not math.isfinite(self.pitch) or self.pitch <= 0:
                raise ValueError(
                    "pitch must be a finite number greater than zero."
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

        for field_name in (
            "language",
            "region",
            "variant",
        ):
            value = getattr(self, field_name)

            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(
                    f"{field_name} must be a non-empty string when provided."
                )

        if self.provider_voice_id is not None and self.provider is None:
            raise ValueError(
                "provider must be provided when provider_voice_id is set."
            )


DEFAULT_VOICE_PROFILES = {
    "female": VoiceProfile(
        voice="female",
    ),
    "male": VoiceProfile(
        voice="male",
    ),
}


class VoiceProfileResolver:
    """
    Resolves application-level voice names into validated voice profiles.

    The resolver deliberately knows nothing about a specific TTS provider.
    """

    def __init__(
        self,
        profiles: Mapping[str, VoiceProfile] | None = None,
    ) -> None:
        source = (
            DEFAULT_VOICE_PROFILES
            if profiles is None
            else profiles
        )

        if not isinstance(source, Mapping):
            raise TypeError("profiles must be a mapping.")

        copied = dict(source)

        for name, profile in copied.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "profile names must be non-empty strings."
                )

            if not isinstance(profile, VoiceProfile):
                raise TypeError(
                    "profiles must contain VoiceProfile instances."
                )

            if profile.voice != name:
                raise ValueError(
                    "profile name must match VoiceProfile.voice."
                )

        self._profiles = copied

    def resolve(self, voice: str) -> VoiceProfile:
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError("voice must be a non-empty string.")

        try:
            return self._profiles[voice]
        except KeyError as exc:
            raise ValueError(
                f"No voice profile configured for '{voice}'."
            ) from exc
