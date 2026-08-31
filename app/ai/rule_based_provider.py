from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage
from app.ai.provider import AIProvider


class RuleBasedAIProvider(AIProvider):
    """Deterministic provider used to validate the assistant pipeline."""

    def interpret(self, message: AssistantMessage) -> AIInterpretation:
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
                target="appointment",
                instruction="No business action required.",
            ),
        )
