from abc import ABC, abstractmethod

from app.ai.context import AIContext
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


class AIProvider(ABC):
    """Canonical intelligence-provider contract."""

    @abstractmethod
    def interpret(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        """Interpret a message using the controlled assistant context."""
        raise NotImplementedError
