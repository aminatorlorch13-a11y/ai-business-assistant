import pytest

from app.voice.request import SpeechRequest, VocalizationEvent


def test_old_speech_request_constructor_remains_compatible():
    request = SpeechRequest(
        text="Hello.",
        voice="female",
        speed=1.0,
    )

    assert request.emotion == "neutral"
    assert request.delivery == "normal"
    assert request.pitch is None
    assert request.vocalizations == ()
    assert request.has_expressive_features is False


def test_request_accepts_expressive_speech():
    request = SpeechRequest(
        text="That is wonderful!",
        voice="female",
        emotion="excited",
        delivery="soft",
        pitch=1.5,
    )

    assert request.emotion == "excited"
    assert request.delivery == "soft"
    assert request.pitch == 1.5
    assert request.has_expressive_features is True


def test_request_accepts_positioned_laughter_and_sigh():
    request = SpeechRequest(
        text="I missed you. I really did.",
        voice="female",
        vocalizations=(
            VocalizationEvent("chuckle", 0, "mild"),
            VocalizationEvent("sigh", 15, "moderate"),
        ),
    )

    assert len(request.vocalizations) == 2
    assert request.vocalizations[0].kind == "chuckle"
    assert request.vocalizations[1].kind == "sigh"


@pytest.mark.parametrize(
    "emotion",
    ["angry", "random", "", None],
)
def test_rejects_unsupported_emotion(emotion):
    with pytest.raises((ValueError, TypeError)):
        SpeechRequest(
            text="Hello.",
            voice="female",
            emotion=emotion,
        )


@pytest.mark.parametrize(
    "delivery",
    ["shouting", "singing", "", None],
)
def test_rejects_unsupported_delivery(delivery):
    with pytest.raises((ValueError, TypeError)):
        SpeechRequest(
            text="Hello.",
            voice="female",
            delivery=delivery,
        )


@pytest.mark.parametrize("pitch", [-7, 7, float("inf"), float("nan"), True])
def test_rejects_invalid_pitch(pitch):
    with pytest.raises(ValueError):
        SpeechRequest(
            text="Hello.",
            voice="female",
            pitch=pitch,
        )


def test_rejects_unknown_vocalization():
    with pytest.raises(ValueError):
        VocalizationEvent("sing", 0)


def test_rejects_negative_vocalization_position():
    with pytest.raises(ValueError):
        VocalizationEvent("laugh", -1)


def test_rejects_vocalization_beyond_text():
    with pytest.raises(ValueError):
        SpeechRequest(
            text="Hello.",
            voice="female",
            vocalizations=(
                VocalizationEvent("laugh", 100),
            ),
        )


def test_rejects_out_of_order_vocalizations():
    with pytest.raises(ValueError):
        SpeechRequest(
            text="Hello. Goodbye.",
            voice="female",
            vocalizations=(
                VocalizationEvent("laugh", 10),
                VocalizationEvent("sigh", 2),
            ),
        )


def test_rejects_non_tuple_vocalizations():
    with pytest.raises(ValueError):
        SpeechRequest(
            text="Hello.",
            voice="female",
            vocalizations=[
                VocalizationEvent("laugh", 0),
            ],
        )
