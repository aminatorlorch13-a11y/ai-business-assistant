from abc import ABC, abstractmethod

from app.assistant.message import AssistantMessage
from app.assistant.response import AssistantResponse


class AIProvider(ABC):
    """Interface for the intelligence provider used by the assistant."""

    @abstractmethod
    def respond(self, message: AssistantMessage) -> AssistantResponse:
        """Generate an assistant response."""
        raise NotImplementedError
