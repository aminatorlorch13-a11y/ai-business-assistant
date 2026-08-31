import subprocess

from app.voice.engine import SpeechEngine
from app.voice.request import SpeechRequest


class AndroidSpeechEngine(SpeechEngine):
    """Speech engine using Android's local text-to-speech capability."""

    def speak(self, request: SpeechRequest) -> None:
        subprocess.run(
            ["termux-tts-speak", request.text],
            check=True,
        )
