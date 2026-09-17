from abc import ABC, abstractmethod

from app.voice.speech_input import SpeechInput


class SpeechInputEngine(ABC):
    """Interface implemented by speech-to-text input engines."""

    @abstractmethod
    def listen(self) -> SpeechInput:
        """Capture one speech recognition result."""
        raise NotImplementedError
