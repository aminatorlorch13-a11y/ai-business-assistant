import pytest

from app.voice.engine import SpeechEngine
from app.voice.request import SpeechRequest, VocalizationEvent


class TestSpeechEngine(SpeechEngine):
    def speak(self, request):
        self.validate_request(request)

    def cancel_current(self):
        pass


def make_request(**changes):
    values = {
        "text": "Hello there.",
        "voice": "male",
    }
    values.update(changes)
    return SpeechRequest(**values)


def test_neutral_request_is_supported():
    engine = TestSpeechEngine()
    engine.validate_request(make_request())


@pytest.mark.parametrize(
    "changes",
    [
        {"emotion": "amused"},
        {"delivery": "whisper"},
        {"pitch": 1.0},
        {
            "vocalizations": (
                VocalizationEvent(kind="laugh", position=0),
            )
        },
    ],
)
def test_unsupported_expressive_features_are_rejected(changes):
    engine = TestSpeechEngine()

    with pytest.raises(
        NotImplementedError,
        match="does not support these speech features",
    ):
        engine.validate_request(make_request(**changes))


def test_invalid_request_type_is_rejected():
    engine = TestSpeechEngine()

    with pytest.raises(TypeError, match="SpeechRequest"):
        engine.validate_request("not a speech request")
