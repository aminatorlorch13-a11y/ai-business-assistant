import pytest

from app.models.voice import VoiceConfiguration


def test_voice_configuration_accepts_valid_data():
    configuration = VoiceConfiguration(
        voice="female",
        speed=1.0,
    )

    assert configuration.voice == "female"
    assert configuration.speed == 1.0


def test_voice_configuration_rejects_unknown_voice():
    with pytest.raises(ValueError):
        VoiceConfiguration(
            voice="robot",
            speed=1.0,
        )


def test_voice_configuration_rejects_zero_speed():
    with pytest.raises(ValueError):
        VoiceConfiguration(
            voice="female",
            speed=0,
        )


def test_voice_configuration_rejects_negative_speed():
    with pytest.raises(ValueError):
        VoiceConfiguration(
            voice="female",
            speed=-1.0,
        )


def test_voice_configuration_rejects_empty_voice():
    with pytest.raises(ValueError, match="voice"):
        VoiceConfiguration(voice="", speed=1.0)


def test_voice_configuration_rejects_boolean_speed():
    with pytest.raises(ValueError, match="speed"):
        VoiceConfiguration(voice="female", speed=True)


def test_voice_configuration_rejects_non_finite_speed():
    with pytest.raises(ValueError, match="finite"):
        VoiceConfiguration(voice="female", speed=float("inf"))
