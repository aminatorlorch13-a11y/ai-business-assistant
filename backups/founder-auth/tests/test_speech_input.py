import pytest

from app.voice.speech_input import SpeechInput


def test_speech_input_accepts_valid_text():
    speech = SpeechInput(text="Hello, this is a voice test.")

    assert speech.text == "Hello, this is a voice test."


def test_speech_input_is_immutable():
    speech = SpeechInput(text="Hello.")

    with pytest.raises(AttributeError):
        speech.text = "Changed."


@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_speech_input_rejects_blank_text(value):
    with pytest.raises(ValueError, match="non-empty"):
        SpeechInput(text=value)


@pytest.mark.parametrize("value", [None, 123, object(), True])
def test_speech_input_rejects_non_string_text(value):
    with pytest.raises(ValueError, match="non-empty"):
        SpeechInput(text=value)
