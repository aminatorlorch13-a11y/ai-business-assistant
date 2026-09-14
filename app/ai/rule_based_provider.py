from app.ai.context import AIContext
from app.ai.provider import AIProvider
from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


class RuleBasedAIProvider(AIProvider):
    """Deterministic provider used to validate the assistant pipeline."""

    def interpret(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> AIInterpretation:
        """Interpret a message using the canonical context-aware contract."""
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if not isinstance(context, AIContext):
            raise TypeError("context must be an AIContext.")

        if context.memory_context.business_id != message.business_id:
            raise ValueError(
                "AI context does not belong to this business."
            )

        return self._interpret_message(message)

    @staticmethod
    def _interpret_message(
        message: AssistantMessage,
    ) -> AIInterpretation:
        content = message.content.lower()

        if "appointment" in content and "create" in content:
            return AIInterpretation(
                intent=AssistantIntent(
                    business_id=message.business_id,
                    intent_type="business_task",
                    instruction="Create an appointment.",
                ),
                action=AssistantAction(
                    business_id=message.business_id,
                    action_type="create",
                    target="appointment",
                    instruction="Create an appointment.",
                ),
            )

        return AIInterpretation(
            intent=AssistantIntent(
                business_id=message.business_id,
                intent_type="general_question",
                instruction="No supported business action identified.",
            ),
            action=AssistantAction(
                business_id=message.business_id,
                action_type="none",
                target="assistant",
                instruction="No business action required.",
            ),
        )
