from typing import Protocol, runtime_checkable

from app.ai.context import AIContext
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


@runtime_checkable
class ContextualAIProvider(Protocol):
    """Optional capability for AI providers that consume controlled context."""

    def interpret_with_context(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        """Interpret a message using controlled AI context."""
        ...
