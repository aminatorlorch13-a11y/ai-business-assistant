import pytest

from app.assistant.response import AssistantResponse
from app.voice.request import SpeechRequest
from app.voice.service import VoiceService


def test_speech_request_accepts_valid_data():
    request = SpeechRequest(
        text="Your business has three important tasks.",
        voice="female",
    )

    assert request.text == "Your business has three important tasks."
    assert request.voice == "female"


def test_voice_service_creates_speech_request():
    service = VoiceService()

    response = AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message="Good morning. You have three important tasks.",
    )

    request = service.create_speech_request(response, "female")

    assert request.text == response.message
    assert request.voice == "female"


def test_voice_service_rejects_response_that_should_not_be_spoken():
    service = VoiceService()

    response = AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message="This should remain silent.",
        should_speak=False,
    )

    with pytest.raises(ValueError):
        service.create_speech_request(response, "female")
