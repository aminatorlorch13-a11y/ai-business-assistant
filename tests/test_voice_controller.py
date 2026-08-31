from unittest.mock import Mock

from app.assistant.response import AssistantResponse
from app.assistant.voice_controller import AssistantVoiceController
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService


def test_voice_controller_sends_response_to_speech_engine():
    voice_service = VoiceService()
    speech_engine = Mock()

    controller = AssistantVoiceController(
        voice_service=voice_service,
        speech_engine=speech_engine,
    )

    response = AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message="Your appointment has been confirmed.",
    )

    controller.speak_response(response, "female")

    speech_engine.speak.assert_called_once_with(
        SpeechRequest(
            text="Your appointment has been confirmed.",
            voice="female",
        )
    )
