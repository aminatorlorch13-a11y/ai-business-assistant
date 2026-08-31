from abc import ABC, abstractmethod

from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


class AIProvider(ABC):
    """Interface for the intelligence provider used by the assistant."""

    @abstractmethod
    def interpret(self, message: AssistantMessage) -> AIInterpretation:
        """Interpret an incoming message into structured assistant instructions."""
        raise NotImplementedError
