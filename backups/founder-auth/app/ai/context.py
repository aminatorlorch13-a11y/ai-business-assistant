from app.assistant.conversation import ConversationHistory
from app.automation.context import AutomationContext
from app.memory.context import MemoryContext


class AIContext:
    """Controlled immutable-by-convention context supplied to an AI provider."""

    def __init__(
        self,
        memory_context: MemoryContext,
        conversation_history: ConversationHistory | None = None,
        automation_context: AutomationContext | None = None,
    ) -> None:
        if not isinstance(memory_context, MemoryContext):
            raise TypeError("memory_context must be a MemoryContext.")

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

        business_id = memory_context.business_id

        if conversation_history is None:
            conversation_history = ConversationHistory(
                business_id=business_id,
            )

        if conversation_history.business_id != business_id:
            raise ValueError(
                "Conversation history does not belong to the memory context business."
            )

        if (
            automation_context is not None
            and automation_context.business_id != business_id
        ):
            raise ValueError(
                "Automation context does not belong to the memory context business."
            )

        self._memory_context = memory_context
        self._conversation_history = conversation_history
        self._automation_context = automation_context

    @property
    def memory_context(self) -> MemoryContext:
        """Return the controlled memory context."""
        return self._memory_context

    @property
    def memory_text(self) -> str:
        """Return formatted memory context for AI consumption."""
        return self._memory_context.as_text()

    @property
    def conversation_history(self) -> ConversationHistory:
        """Return the bounded prior conversational history."""
        return self._conversation_history

    @property
    def automation_context(self) -> AutomationContext | None:
        """Return trusted automation context when supplied."""
        return self._automation_context
