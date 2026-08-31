from app.assistant.response import AssistantResponse
from app.voice.engine import SpeechEngine
from app.voice.service import VoiceService


class AssistantVoiceController:
    """Coordinates assistant responses with the configured speech engine."""

    def __init__(
        self,
        voice_service: VoiceService,
        speech_engine: SpeechEngine,
    ) -> None:
        self._voice_service = voice_service
        self._speech_engine = speech_engine

    def speak_response(
        self,
        response: AssistantResponse,
        voice: str,
    ) -> None:
        """Speak an assistant response using the selected voice."""

        speech_request = self._voice_service.create_speech_request(
            response,
            voice,
        )

        self._speech_engine.speak(speech_request)
