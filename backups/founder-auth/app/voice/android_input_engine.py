import subprocess

from app.voice.input_engine import SpeechInputEngine
from app.voice.speech_input import SpeechInput


class AndroidSpeechInputEngine(SpeechInputEngine):
    """Speech-to-text engine using Android's local Termux API."""

    COMMAND = "termux-speech-to-text"

    def listen(self) -> SpeechInput:
        """Capture one speech recognition result from Android STT."""
        try:
            completed = subprocess.run(
                [self.COMMAND],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Android speech recognition failed."
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                "Android speech recognition command is unavailable."
            ) from exc

        text = completed.stdout.strip()

        if not text:
            raise RuntimeError(
                "Android speech recognition returned no usable text."
            )

        return SpeechInput(text=text)
