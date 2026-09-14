from collections.abc import Mapping

from app.ai.context import AIContext
from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage


class DeterministicRawAIProvider(RawAIProvider):
    """Deterministic raw provider used to exercise the AI pipeline."""

    def generate(
        self,
        message: AssistantMessage,
        context: AIContext,
    ) -> Mapping[str, object]:
        """Return predictable raw AI output for supported messages."""
        if not isinstance(message, AssistantMessage):
            raise TypeError("message must be an AssistantMessage.")

        if not isinstance(context, AIContext):
            raise TypeError("context must be an AIContext.")

        if context.memory_context.business_id != message.business_id:
            raise ValueError(
                "AI context does not belong to this business."
            )

        if message.content.strip().lower() == "please create an appointment.":
            return {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
                "business_id": message.business_id,
            }

        return {
            "intent_type": "general_question",
            "instruction": "No business action required.",
            "action_type": "none",
            "target": "assistant",
            "action_instruction": "No business action required.",
            "business_id": message.business_id,
        }
