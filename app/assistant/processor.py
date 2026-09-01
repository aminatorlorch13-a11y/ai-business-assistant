from app.ai.context import AIContext
from app.ai.contextual_provider import ContextualAIProvider
from app.automation.context import AutomationContext
from app.ai.provider import AIProvider
from app.assistant.interpretation import AIInterpretation
from app.assistant.interpretation_validator import AIInterpretationValidator
from app.assistant.message import AssistantMessage
from app.memory.context import MemoryContextBuilder


class AssistantProcessor:
    """Coordinates AI interpretation, controlled context, and validation."""

    def __init__(
        self,
        ai_provider: AIProvider,
        validator: AIInterpretationValidator,
        memory_context_builder: MemoryContextBuilder | None = None,
    ) -> None:
        if not isinstance(ai_provider, AIProvider):
            raise TypeError("ai_provider must be an AIProvider.")

        if not isinstance(validator, AIInterpretationValidator):
            raise TypeError(
                "validator must be an AIInterpretationValidator."
            )

        if memory_context_builder is not None and not isinstance(
            memory_context_builder,
            MemoryContextBuilder,
        ):
            raise TypeError(
                "memory_context_builder must be a MemoryContextBuilder or None."
            )

        self._ai_provider = ai_provider
        self._validator = validator
        self._memory_context_builder = memory_context_builder

    def process(
        self,
        message: AssistantMessage,
        automation_context: AutomationContext | None = None,
    ) -> AIInterpretation:
        """Interpret, optionally contextualize, and validate one message."""

        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if automation_context is not None and not isinstance(
            automation_context,
            AutomationContext,
        ):
            raise TypeError(
                "automation_context must be an AutomationContext or None."
            )

        if (
            automation_context is not None
            and automation_context.business_id != message.business_id
        ):
            raise ValueError(
                "Automation context does not belong to this message business."
            )

        interpretation = self._interpret(
            message,
            automation_context=automation_context,
        )

        if not isinstance(interpretation, AIInterpretation):
            raise TypeError(
                "AI provider must return an AIInterpretation."
            )

        validated = self._validator.validate(
            interpretation,
            business_id=message.business_id,
        )

        if not isinstance(validated, AIInterpretation):
            raise TypeError(
                "validator must return an AIInterpretation."
            )

        return validated

    def _interpret(
        self,
        message: AssistantMessage,
        automation_context: AutomationContext | None = None,
    ) -> AIInterpretation:
        """Select the safest supported provider interpretation path."""

        if (
            self._memory_context_builder is not None
            and isinstance(self._ai_provider, ContextualAIProvider)
        ):
            memory_context = self._memory_context_builder.build(
                message.business_id
            )

            context = AIContext(
                memory_context,
                automation_context=automation_context,
            )

            return self._ai_provider.interpret_with_context(
                message,
                context,
            )

        return self._ai_provider.interpret(message)
