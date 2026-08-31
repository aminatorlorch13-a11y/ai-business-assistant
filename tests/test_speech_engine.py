from unittest.mock import patch

from app.voice.local_engine import AndroidSpeechEngine
from app.voice.request import SpeechRequest


def test_android_speech_engine_calls_termux_tts():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="The assistant is ready.",
        voice="female",
    )

    with patch("subprocess.run") as run:
        engine.speak(request)

    run.assert_called_once_with(
        ["termux-tts-speak", "The assistant is ready."],
        check=True,
    )
