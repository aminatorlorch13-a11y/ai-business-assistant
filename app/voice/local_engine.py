import subprocess

from app.voice.engine import SpeechEngine
from app.voice.request import SpeechRequest


class AndroidSpeechEngine(SpeechEngine):
    """Speech engine using Android's local text-to-speech capability."""

    def speak(self, request: SpeechRequest) -> None:
        """Speak a validated speech request."""

        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest.")

        subprocess.run(
            [
                "termux-tts-speak",
                "-r",
                str(request.speed),
                request.text,
            ],
            check=True,
        )
