from abc import ABC, abstractmethod
from collections.abc import Mapping

from app.assistant.message import AssistantMessage


class RawAIProvider(ABC):
    """Interface for providers that return raw structured AI output."""

    @abstractmethod
    def generate(self, message: AssistantMessage) -> Mapping[str, object]:
        """Generate structured raw output for an assistant message."""
        raise NotImplementedError
