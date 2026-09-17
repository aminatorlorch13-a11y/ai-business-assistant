from typing import Protocol, runtime_checkable

from app.ai.context import AIContext
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


@runtime_checkable
class ContextualAIProvider(Protocol):
    """Deprecated compatibility protocol.

    Context is now a mandatory part of the AIProvider contract.
    New providers must implement AIProvider.interpret(message, context)
    directly rather than relying on this optional protocol.
    """

    def interpret_with_context(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        """Legacy contextual-provider capability."""
        ...
