from abc import ABC, abstractmethod
from collections.abc import Mapping

from app.ai.context import AIContext
from app.assistant.message import AssistantMessage


class RawAIProvider(ABC):
    """Interface for providers that return raw structured AI output."""

    @abstractmethod
    def generate(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> Mapping[str, object]:
        """Generate structured raw output using controlled assistant context."""
        raise NotImplementedError
