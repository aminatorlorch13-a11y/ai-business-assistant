from app.automation.context import AutomationContext
from app.memory.context import MemoryContext


class AIContext:
    """Controlled context supplied to an AI provider."""

    def __init__(
        self,
        memory_context: MemoryContext,
        automation_context: AutomationContext | None = None,
    ) -> None:
        if not isinstance(memory_context, MemoryContext):
            raise TypeError("memory_context must be a MemoryContext.")

        if automation_context is not None and not isinstance(
            automation_context,
            AutomationContext,
        ):
            raise TypeError(
                "automation_context must be an AutomationContext or None."
            )

        if (
            automation_context is not None
            and automation_context.business_id
            != memory_context.business_id
        ):
            raise ValueError(
                "Automation context does not belong to the memory context business."
            )

        self._memory_context = memory_context
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
    def automation_context(self) -> AutomationContext | None:
        """Return trusted automation context when supplied."""
        return self._automation_context
