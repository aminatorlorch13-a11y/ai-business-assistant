from abc import ABC, abstractmethod

from app.voice.request import SpeechRequest


class SpeechEngine(ABC):
    """Interface implemented by every speech engine."""

    @abstractmethod
    def speak(self, request: SpeechRequest) -> None:
        """Speak the supplied speech request."""
        raise NotImplementedError
