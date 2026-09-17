import pytest
from unittest.mock import Mock

from app.assistant.response import AssistantResponse
from app.assistant.voice_controller import AssistantVoiceController
from app.models.voice import VoiceConfiguration
from app.voice.engine import SpeechEngine
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService


def make_response() -> AssistantResponse:
    return AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message="Your appointment has been confirmed.",
    )


def make_configuration() -> VoiceConfiguration:
    return VoiceConfiguration(
        voice="female",
        speed=1.0,
    )


def test_voice_controller_sends_response_to_speech_engine():
    voice_service = VoiceService()
    speech_engine = Mock(spec=SpeechEngine)

    controller = AssistantVoiceController(
        voice_service=voice_service,
        speech_engine=speech_engine,
    )

    controller.speak_response(
        make_response(),
        make_configuration(),
    )

    speech_engine.speak.assert_called_once_with(
        SpeechRequest(
            text="Your appointment has been confirmed.",
            voice="female",
        )
    )


def test_voice_controller_rejects_invalid_response():
    controller = AssistantVoiceController(
        voice_service=VoiceService(),
        speech_engine=Mock(spec=SpeechEngine),
    )

    with pytest.raises(TypeError, match="response"):
        controller.speak_response(
            object(),
            make_configuration(),
        )


def test_voice_controller_rejects_invalid_configuration():
    controller = AssistantVoiceController(
        voice_service=VoiceService(),
        speech_engine=Mock(spec=SpeechEngine),
    )

    with pytest.raises(TypeError, match="configuration"):
        controller.speak_response(
            make_response(),
            object(),
        )


def test_voice_controller_rejects_invalid_voice_configuration():
    controller = AssistantVoiceController(
        voice_service=VoiceService(),
        speech_engine=Mock(spec=SpeechEngine),
    )

    with pytest.raises(ValueError, match="voice"):
        controller.speak_response(
            make_response(),
            VoiceConfiguration(voice="robot"),
        )
