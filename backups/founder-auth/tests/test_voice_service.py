import pytest

from app.assistant.response import AssistantResponse
from app.models.voice import VoiceConfiguration
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService


def make_response(
    message: str = "Good morning. You have three important tasks.",
    should_speak: bool = True,
) -> AssistantResponse:
    return AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message=message,
        should_speak=should_speak,
    )


def make_configuration(
    voice: str = "female",
    speed: float = 1.0,
) -> VoiceConfiguration:
    return VoiceConfiguration(
        voice=voice,
        speed=speed,
    )


def test_voice_service_creates_speech_request():
    service = VoiceService()

    response = make_response()
    configuration = make_configuration()

    request = service.create_speech_request(
        response,
        configuration,
    )

    assert request == SpeechRequest(
        text=response.message,
        voice="female",
    )


def test_voice_service_rejects_response_that_should_not_be_spoken():
    service = VoiceService()

    response = make_response(
        message="This should remain silent.",
        should_speak=False,
    )
    configuration = make_configuration()

    with pytest.raises(ValueError, match="should not be spoken"):
        service.create_speech_request(
            response,
            configuration,
        )


def test_voice_service_rejects_invalid_response():
    service = VoiceService()
    configuration = make_configuration()

    with pytest.raises(TypeError, match="response"):
        service.create_speech_request(
            object(),
            configuration,
        )


def test_voice_service_rejects_invalid_configuration():
    service = VoiceService()
    response = make_response()

    with pytest.raises(TypeError, match="configuration"):
        service.create_speech_request(
            response,
            object(),
        )


def test_voice_service_rejects_unknown_voice():
    service = VoiceService()
    response = make_response()

    with pytest.raises(ValueError, match="voice"):
        service.create_speech_request(
            response,
            VoiceConfiguration(voice="robot"),
        )
