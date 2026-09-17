from app.assistant.response import AssistantResponse
from app.models.voice import VoiceConfiguration
from app.voice.request import SpeechRequest


class VoiceService:
    """Converts valid assistant responses into speech requests."""

    def create_speech_request(
        self,
        response: AssistantResponse,
        configuration: VoiceConfiguration,
    ) -> SpeechRequest:
        """Create a speech request from an assistant response."""

        if not isinstance(response, AssistantResponse):
            raise TypeError("response must be an AssistantResponse.")

        if not isinstance(configuration, VoiceConfiguration):
            raise TypeError("configuration must be a VoiceConfiguration.")

        if not response.should_speak:
            raise ValueError(
                "This assistant response should not be spoken."
            )

        return SpeechRequest(
            text=response.message,
            voice=configuration.voice,
            speed=configuration.speed,
        )
