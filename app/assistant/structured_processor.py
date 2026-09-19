from __future__ import annotations

from app.ai.context import AIContext
from app.ai.structured_provider import StructuredAIProvider
from app.assistant.ai_result import AIResult
from app.assistant.conversation import ConversationHistory
from app.assistant.message import AssistantMessage
from app.automation.context import AutomationContext
from app.memory.context import MemoryContextBuilder


class StructuredAssistantProcessor:
    """
    Coordinates structured AI processing up to the AIResult boundary.

    This processor is intentionally limited to:
    - validating message/context ownership,
    - building controlled AI context,
    - invoking the structured AI provider,
    - validating the provider's AIResult boundary.

    It does not authorize, execute, or construct CapabilityExecutionRequest
    objects. Those responsibilities belong to the orchestration layer.
    """

    def __init__(
        self,
        ai_provider: StructuredAIProvider,
        memory_context_builder: MemoryContextBuilder | None = None,
    ) -> None:
        if not isinstance(ai_provider, StructuredAIProvider):
            raise TypeError(
                "ai_provider must be a StructuredAIProvider."
            )

        if (
            memory_context_builder is not None
            and not isinstance(memory_context_builder, MemoryContextBuilder)
        ):
            raise TypeError(
                "memory_context_builder must be a MemoryContextBuilder or None."
            )

        self._ai_provider = ai_provider
        self._memory_context_builder = memory_context_builder

    def process(
        self,
        message: AssistantMessage,
        automation_context: AutomationContext | None = None,
        conversation_history: ConversationHistory | None = None,
    ) -> AIResult:
        """Generate one validated AIResult from controlled application context."""
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if conversation_history is not None and not isinstance(
            conversation_history,
            ConversationHistory,
        ):
            raise TypeError(
                "conversation_history must be a ConversationHistory or None."
            )

        if automation_context is not None and not isinstance(
            automation_context,
            AutomationContext,
        ):
            raise TypeError(
                "automation_context must be an AutomationContext or None."
            )

        if (
            conversation_history is not None
            and conversation_history.business_id != message.business_id
        ):
            raise ValueError(
                "Conversation history does not belong to this message business."
            )

        if (
            automation_context is not None
            and automation_context.business_id != message.business_id
        ):
            raise ValueError(
                "Automation context does not belong to this message business."
            )

        result = self._generate(
            message,
            automation_context=automation_context,
            conversation_history=conversation_history,
        )

        if not isinstance(result, AIResult):
            raise TypeError(
                "AI provider must return an AIResult."
            )

        return result

    def _generate(
        self,
        message: AssistantMessage,
        automation_context: AutomationContext | None = None,
        conversation_history: ConversationHistory | None = None,
    ) -> AIResult:
        """Build controlled context and invoke the structured provider."""
        if self._memory_context_builder is None:
            raise RuntimeError(
                "A MemoryContextBuilder is required for AI processing."
            )

        memory_context = self._memory_context_builder.build(
            message.business_id
        )

        context = AIContext(
            memory_context,
            conversation_history=conversation_history,
            automation_context=automation_context,
        )

        return self._ai_provider.generate(
            message,
            context,
        )
