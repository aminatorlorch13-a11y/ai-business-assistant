"""Server-side ElevenLabs speech synthesis for the Amination web assistant."""

from __future__ import annotations

import json
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
    model_id: str = "eleven_flash_v2_5"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("ElevenLabs API key is required.")
        if not self.male_voice_id.strip() or not self.female_voice_id.strip():
            raise ValueError("Both ElevenLabs voice IDs are required.")
        if not self.model_id.strip():
            raise ValueError("ElevenLabs model ID is required.")
        if self.timeout_seconds <= 0:
            raise ValueError("ElevenLabs timeout must be positive.")

    @classmethod
    def from_environment(cls) -> "ElevenLabsConfig":
        values = {
            "api_key": os.getenv("ELEVENLABS_API_KEY", "").strip(),
            "male_voice_id": os.getenv("ELEVENLABS_VOICE_ID_MALE", "").strip(),
            "female_voice_id": os.getenv("ELEVENLABS_VOICE_ID_FEMALE", "").strip(),
        }

        if not all(values.values()):
            raise RuntimeError(
                "ElevenLabs is not configured. Set its API key and both voice IDs."
            )

        timeout_value = os.getenv("ELEVENLABS_TIMEOUT_SECONDS", "30")

        try:
            timeout_seconds = float(timeout_value)
        except ValueError as exc:
            raise RuntimeError("Invalid ElevenLabs timeout configuration.") from exc

        return cls(
            **values,
            model_id=os.getenv(
                "ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"
            ).strip(),
            timeout_seconds=timeout_seconds,
        )


class ElevenLabsSpeechEngine:
    """Generate actual MP3 audio bytes; playback is handled by the web browser."""

    ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"
    OUTPUT_FORMAT = "mp3_44100_128"
    MAX_AUDIO_BYTES = 20 * 1024 * 1024

    def __init__(self, config: ElevenLabsConfig) -> None:
        if not isinstance(config, ElevenLabsConfig):
            raise TypeError("config must be an ElevenLabsConfig.")
        self._config = config

    def synthesize(self, speech_request: SpeechRequest) -> bytes:
        if not isinstance(speech_request, SpeechRequest):
            raise TypeError("speech_request must be a SpeechRequest.")

        voice_id = {
            "male": self._config.male_voice_id,
            "female": self._config.female_voice_id,
        }.get(speech_request.voice)

        if voice_id is None:
            raise ValueError("Unsupported voice selection.")

        if not 0.7 <= speech_request.speed <= 1.2:
            raise ValueError("ElevenLabs speech speed must be between 0.7 and 1.2.")

        url = (
            f"{self.ENDPOINT}/{quote(voice_id, safe='')}/stream"
            f"?output_format={self.OUTPUT_FORMAT}"
        )

        payload = {
            "text": speech_request.text,
            "model_id": self._config.model_id,
            "voice_settings": {
                "speed": speech_request.speed,
            },
        }

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
                request, timeout=self._config.timeout_seconds
            ) as response:
                audio = response.read(self.MAX_AUDIO_BYTES + 1)
        except HTTPError as exc:
            # Do not expose provider response bodies or credentials to users.
            raise RuntimeError(
                f"ElevenLabs speech request failed (HTTP {exc.code})."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError(
                "ElevenLabs could not be reached. Please try again."
            ) from None

        if not audio:
            raise RuntimeError("ElevenLabs returned empty audio.")
        if len(audio) > self.MAX_AUDIO_BYTES:
            raise RuntimeError("ElevenLabs audio response exceeded the size limit.")

        return audio
