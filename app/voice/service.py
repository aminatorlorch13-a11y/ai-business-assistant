from app.assistant.response import AssistantResponse
from app.voice.request import SpeechRequest


class VoiceService:
    """Converts assistant responses into speech requests."""

    def create_speech_request(
        self,
        response: AssistantResponse,
        voice: str,
    ) -> SpeechRequest:
        """Create a speech request from an assistant response."""

        if not response.should_speak:
            raise ValueError("This assistant response should not be spoken.")

        return SpeechRequest(
            text=response.message,
            voice=voice,
        )
