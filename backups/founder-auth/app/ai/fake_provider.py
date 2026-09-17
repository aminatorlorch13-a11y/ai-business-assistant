from app.ai.provider import AIProvider
from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation
from app.assistant.message import AssistantMessage


class FakeAIProvider(AIProvider):
    """Deterministic AI provider used for development and testing."""

    def interpret(self, message: AssistantMessage) -> AIInterpretation:
        """Return a deterministic interpretation for a test message."""

        if message.content.strip().lower() == "please create an appointment.":
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
                instruction="No business action required.",
            ),
            action=AssistantAction(
                business_id=message.business_id,
                action_type="none",
                target="assistant",
                instruction="No business action required.",
            ),
        )
