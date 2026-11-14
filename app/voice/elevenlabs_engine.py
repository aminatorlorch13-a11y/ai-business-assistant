"""Server-side ElevenLabs speech synthesis for the Amination web assistant."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.voice.request import SpeechRequest


@dataclass(frozen=True)
class ElevenLabsConfig:
    api_key: str
    male_voice_id: str
    female_voice_id: str
    model_id: str = "eleven_v4_turbo"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("ElevenLabs API key is required.")

        if (
            not isinstance(self.male_voice_id, str)
            or not self.male_voice_id.strip()
            or not isinstance(self.female_voice_id, str)
            or not self.female_voice_id.strip()
        ):
            raise ValueError("Both ElevenLabs voice IDs are required.")

        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("ElevenLabs model ID is required.")

        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError(
                "ElevenLabs timeout must be positive and finite."
            )

    @classmethod
    def from_environment(cls) -> "ElevenLabsConfig":
        values = {
            "api_key": os.getenv("ELEVENLABS_API_KEY", "").strip(),
            "male_voice_id": os.getenv(
                "ELEVENLABS_VOICE_ID_MALE", ""
            ).strip(),
            "female_voice_id": os.getenv(
                "ELEVENLABS_VOICE_ID_FEMALE", ""
            ).strip(),
        }

        if not all(values.values()):
            raise RuntimeError(
                "ElevenLabs is not configured. Set its API key and both voice IDs."
            )

        timeout_value = os.getenv(
            "ELEVENLABS_TIMEOUT_SECONDS", "30"
        )

        try:
            timeout_seconds = float(timeout_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Invalid ElevenLabs timeout configuration."
            ) from exc

        return cls(
            **values,
            model_id=os.getenv(
                "ELEVENLABS_MODEL_ID", "eleven_v4_turbo"
            ).strip(),
            timeout_seconds=timeout_seconds,
        )


class ElevenLabsSpeechEngine:
    """Generate actual MP3 audio bytes; playback is handled by the web browser."""

    ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"
    OUTPUT_FORMAT = "mp3_44100_128"
    MAX_AUDIO_BYTES = 20 * 1024 * 1024

    TAG_SUPPORTED_MODELS = frozenset({
        "eleven_v3",
        "eleven_v4",
        "eleven_v4_turbo",
    })

    VOCALIZATION_TAGS = {
        "laugh": "[laughs]",
        "chuckle": "[chuckles]",
        "sigh": "[sighs]",
        "breath": "[exhales]",
    }

    EMOTION_TAGS = {
        "amused": "[mischievously]",
        "excited": "[excited]",
        "curious": "[curious]",
        "sad": "[sad]",
        "empathetic": "[empathetically]",
        "serious": "[seriously]",
        "soothing": "[soothingly]",
    }

    DELIVERY_TAGS = {
        "soft": "[softly]",
        "whisper": "[whispers]",
    }

    def __init__(self, config: ElevenLabsConfig) -> None:
        if not isinstance(config, ElevenLabsConfig):
            raise TypeError(
                "config must be an ElevenLabsConfig."
            )

        self._config = config

    def _prepare_expressive_text(
        self,
        speech_request: SpeechRequest,
    ) -> str:
        """Render expressive instructions as model-compatible audio tags."""

        if not isinstance(speech_request, SpeechRequest):
            raise TypeError(
                "speech_request must be a SpeechRequest."
            )

        model_id = self._config.model_id

        needs_audio_tags = bool(
            speech_request.vocalizations
            or speech_request.emotion != "neutral"
            or speech_request.delivery != "normal"
        )

        if model_id not in self.TAG_SUPPORTED_MODELS:
            if needs_audio_tags:
                raise ValueError(
                    "This ElevenLabs model does not support expressive audio tags. "
                    "Use a compatible expressive model to enable vocal expressions."
                )

            return speech_request.text

        if speech_request.pitch is not None:
            raise ValueError(
                "Numeric pitch control is not implemented for this "
                "ElevenLabs model."
            )

        if speech_request.speed != 1.0:
            raise ValueError(
                "This ElevenLabs expressive model does not support "
                "the numeric speed setting. Use speed=1.0."
            )

        text = speech_request.text
        pieces: list[str] = []
        cursor = 0

        for event in speech_request.vocalizations:
            if event.kind not in self.VOCALIZATION_TAGS:
                raise ValueError(
                    f"Unsupported vocalization: {event.kind}"
                )

            if event.position > len(text):
                raise ValueError(
                    "Vocalization position exceeds the speech text length."
                )

            if event.intensity != "moderate":
                raise ValueError(
                    "Non-moderate vocalization intensity is not yet "
                    "implemented for ElevenLabs."
                )

            segment = text[cursor:event.position]
            pieces.append(segment)

            tag = self.VOCALIZATION_TAGS[event.kind]

            # Keep tags separated from surrounding words without
            # changing the actual spoken sentence.
            if segment and not segment[-1].isspace():
                pieces.append(" ")

            pieces.append(tag)

            if (
                event.position < len(text)
                and not text[event.position].isspace()
            ):
                pieces.append(" ")

            cursor = event.position

        pieces.append(text[cursor:])
        rendered = "".join(pieces).strip()

        # Keep a predictable order: emotion first, delivery second.
        prefix: list[str] = []

        if speech_request.emotion != "neutral":
            emotion_tag = self.EMOTION_TAGS.get(
                speech_request.emotion
            )

            if emotion_tag is None:
                raise ValueError(
                    f"Unsupported emotion: {speech_request.emotion}"
                )

            prefix.append(emotion_tag)

        if speech_request.delivery != "normal":
            delivery_tag = self.DELIVERY_TAGS.get(
                speech_request.delivery
            )

            if delivery_tag is None:
                raise ValueError(
                    f"Unsupported delivery: {speech_request.delivery}"
                )

            prefix.append(delivery_tag)

        if prefix:
            rendered = " ".join(prefix + [rendered])

        return rendered

    def _build_payload(
        self,
        speech_request: SpeechRequest,
    ) -> dict:
        """Build a request appropriate for the configured model."""

        expressive_text = self._prepare_expressive_text(
            speech_request
        )

        payload = {
            "text": expressive_text,
            "model_id": self._config.model_id,
        }

        if self._config.model_id not in self.TAG_SUPPORTED_MODELS:
            if not 0.7 <= speech_request.speed <= 1.2:
                raise ValueError(
                    "ElevenLabs speech speed must be between 0.7 and 1.2."
                )

            payload["voice_settings"] = {
                "speed": speech_request.speed,
            }

        return payload

    def synthesize(self, speech_request: SpeechRequest) -> bytes:
        """Generate MP3 bytes using the configured ElevenLabs voice."""

        if not isinstance(speech_request, SpeechRequest):
            raise TypeError(
                "speech_request must be a SpeechRequest."
            )

        voice_id = {
            "male": self._config.male_voice_id,
            "female": self._config.female_voice_id,
        }.get(speech_request.voice)

        if voice_id is None:
            raise ValueError("Unsupported voice selection.")

        payload = self._build_payload(speech_request)

        url = (
            f"{self.ENDPOINT}/{quote(voice_id, safe='')}/stream"
            f"?output_format={self.OUTPUT_FORMAT}"
        )

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "xi-api-key": self._config.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                audio = response.read(
                    self.MAX_AUDIO_BYTES + 1
                )

        except HTTPError as exc:
            raise RuntimeError(
                f"ElevenLabs speech request failed (HTTP {exc.code})."
            ) from None

        except (URLError, TimeoutError, OSError):
            raise RuntimeError(
                "ElevenLabs could not be reached. Please try again."
            ) from None

        if not audio:
            raise RuntimeError(
                "ElevenLabs returned empty audio."
            )

        if len(audio) > self.MAX_AUDIO_BYTES:
            raise RuntimeError(
                "ElevenLabs audio response exceeded the size limit."
            )

        return audio
