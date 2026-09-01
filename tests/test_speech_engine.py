import pytest
from unittest.mock import patch

from app.voice.local_engine import AndroidSpeechEngine
from app.voice.request import SpeechRequest


def test_android_speech_engine_calls_termux_tts():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="The assistant is ready.",
        voice="female",
        speed=1.0,
    )

    with patch("subprocess.run") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "1.0",
            "The assistant is ready.",
        ],
        check=True,
    )


def test_android_speech_engine_passes_custom_speed():
    engine = AndroidSpeechEngine()

    request = SpeechRequest(
        text="Speak more slowly.",
        voice="female",
        speed=0.75,
    )

    with patch("subprocess.run") as run:
        engine.speak(request)

    run.assert_called_once_with(
        [
            "termux-tts-speak",
            "-r",
            "0.75",
            "Speak more slowly.",
        ],
        check=True,
    )


def test_android_speech_engine_rejects_invalid_request():
    engine = AndroidSpeechEngine()

    with pytest.raises(TypeError, match="request"):
        engine.speak(object())
