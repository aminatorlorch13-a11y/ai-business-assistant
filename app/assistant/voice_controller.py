from app.assistant.response import AssistantResponse
from app.models.voice import VoiceConfiguration
from app.voice.engine import SpeechEngine
from app.voice.service import VoiceService


class AssistantVoiceController:
    """Coordinates assistant responses with the configured speech engine."""

    def __init__(
        self,
        voice_service: VoiceService,
        speech_engine: SpeechEngine,
    ) -> None:
        if not isinstance(voice_service, VoiceService):
            raise TypeError("voice_service must be a VoiceService.")

        if not isinstance(speech_engine, SpeechEngine):
            raise TypeError("speech_engine must be a SpeechEngine.")

        self._voice_service = voice_service
        self._speech_engine = speech_engine

    def speak_response(
        self,
        response: AssistantResponse,
        configuration: VoiceConfiguration,
    ) -> None:
        """Speak an assistant response using the selected configuration."""

        if not isinstance(response, AssistantResponse):
            raise TypeError("response must be an AssistantResponse.")

        if not isinstance(configuration, VoiceConfiguration):
            raise TypeError("configuration must be a VoiceConfiguration.")

        speech_request = self._voice_service.create_speech_request(
            response,
            configuration,
        )

        self._speech_engine.speak(speech_request)
