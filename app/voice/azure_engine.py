from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from xml.sax.saxutils import escape

from app.voice.engine import SpeechEngine
from app.voice.profile import VoiceProfile, VoiceProfileResolver
from app.voice.request import SpeechRequest


@dataclass(frozen=True)
class AzureSpeechConfig:
    subscription_key: str
    region: str
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.subscription_key, str) or not self.subscription_key.strip():
            raise ValueError("Azure Speech subscription key is required.")

        if not isinstance(self.region, str) or not re.fullmatch(
            r"[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?",
            self.region.strip().lower(),
        ):
            raise ValueError("A valid Azure Speech region is required.")

        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Azure Speech timeout must be positive.")

    @classmethod
    def from_environment(cls) -> "AzureSpeechConfig":
        key = os.getenv("AZURE_SPEECH_KEY", "")
        region = os.getenv("AZURE_SPEECH_REGION", "")
        timeout = os.getenv("AZURE_SPEECH_TIMEOUT_SECONDS", "30")

        try:
            timeout_seconds = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("AZURE_SPEECH_TIMEOUT_SECONDS must be numeric.") from exc

        return cls(
            subscription_key=key,
            region=region,
            timeout_seconds=timeout_seconds,
        )


AZURE_VOICE_PROFILES = {
    "female": VoiceProfile(
        voice="female",
        provider="azure",
        provider_voice_id="en-ZA-LeahNeural",
        language="en-ZA",
    ),
    "male": VoiceProfile(
        voice="male",
        provider="azure",
        provider_voice_id="en-ZA-LukeNeural",
        language="en-ZA",
    ),
}


class AzureSpeechEngine(SpeechEngine):
    """Azure neural speech synthesis with Termux MP3 playback."""

    OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
    MEDIA_PLAYER = "termux-media-player"
    POLL_INTERVAL_SECONDS = 0.25
    MAX_PLAYBACK_SECONDS = 900
    PLAYBACK_START_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        config: AzureSpeechConfig,
        profile_resolver: VoiceProfileResolver | None = None,
    ) -> None:
        if not isinstance(config, AzureSpeechConfig):
            raise TypeError("config must be an AzureSpeechConfig.")

        self._config = config
        self._profiles = profile_resolver or VoiceProfileResolver(
            AZURE_VOICE_PROFILES
        )
        self._lock = threading.RLock()
        self._active_file: str | None = None
        self._speaking = False
        self._cancelled = threading.Event()

    def _build_ssml(self, request: SpeechRequest) -> str:
        profile = self._profiles.resolve(request.voice)

        if profile.provider != "azure" or not profile.provider_voice_id:
            raise ValueError("The selected voice profile is not configured for Azure.")

        if profile.language is None:
            raise ValueError("The Azure voice profile must define its language.")

        speed = request.speed * profile.speed
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Azure speech speed must be between 0.5 and 2.0.")

        safe_text = escape(request.text)
        safe_voice = escape(profile.provider_voice_id)
        safe_language = escape(profile.language)

        return (
            '<speak version="1.0" '
            'xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="{safe_language}">'
            f'<voice name="{safe_voice}">'
            f'<prosody rate="{speed * 100:.0f}%">{safe_text}</prosody>'
            '</voice></speak>'
        )

    def _synthesize(self, ssml: str) -> bytes:
        endpoint = (
            f"https://{self._config.region}.tts.speech.microsoft.com"
            "/cognitiveservices/v1"
        )

        request = urllib.request.Request(
            endpoint,
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": self._config.subscription_key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": self.OUTPUT_FORMAT,
                "User-Agent": "Amination-AI",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            # Never expose the response body or credentials.
            raise RuntimeError(
                f"Azure Speech request failed with HTTP {exc.code}."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError(
                "Azure Speech could not be reached. Check the network and region."
            ) from None

        if not audio:
            raise RuntimeError("Azure Speech returned an empty audio response.")

        return audio

    def _player(self, *args: str) -> str:
        result = subprocess.run(
            [self.MEDIA_PLAYER, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("Termux media player command failed.")
        return (result.stdout or result.stderr).strip()

    def speak(self, request: SpeechRequest) -> None:
        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest.")

        self.validate_request(request)

        ssml = self._build_ssml(request)

        with self._lock:
            if self._speaking:
                raise RuntimeError("Speech playback is already active.")
            self._speaking = True
            self._cancelled.clear()

        temp_path: str | None = None

        try:
            audio = self._synthesize(ssml)

            if self._cancelled.is_set():
                return

            with tempfile.NamedTemporaryFile(
                prefix="amination-tts-",
                suffix=".mp3",
                delete=False,
            ) as audio_file:
                temp_path = audio_file.name
                audio_file.write(audio)

            with self._lock:
                if self._cancelled.is_set():
                    return
                self._active_file = temp_path

            self._player("play", temp_path)

            started = time.monotonic()
            playback_started = False

            while not self._cancelled.is_set():
                elapsed = time.monotonic() - started

                if elapsed > self.MAX_PLAYBACK_SECONDS:
                    self._player("stop")
                    raise TimeoutError(
                        "Speech playback exceeded its safety timeout."
                    )

                status = self._player("info")
                idle = "no track currently" in status.lower()

                if not idle:
                    playback_started = True
                elif playback_started:
                    break
                elif elapsed > self.PLAYBACK_START_TIMEOUT_SECONDS:
                    raise RuntimeError(
                        "Termux media player did not start audio playback."
                    )

                time.sleep(self.POLL_INTERVAL_SECONDS)

        finally:
            with self._lock:
                if self._active_file == temp_path:
                    self._active_file = None
                self._speaking = False

            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    def cancel_current(self) -> None:
        with self._lock:
            if not self._speaking:
                return

            self._cancelled.set()
            should_stop = self._active_file is not None

        if should_stop:
            self._player("stop")
