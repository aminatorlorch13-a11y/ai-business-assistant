from collections.abc import Mapping

from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage


class DeterministicRawAIProvider(RawAIProvider):
    """Deterministic raw provider used to exercise the AI pipeline."""

    def generate(self, message: AssistantMessage) -> Mapping[str, object]:
        """Return predictable raw AI output for supported messages."""
        if message.content.strip().lower() == "please create an appointment.":
            return {
                "intent_type": "business_task",
                "instruction": "Create an appointment.",
                "action_type": "create",
                "target": "appointment",
                "action_instruction": "Create an appointment.",
            }

        return {
            "intent_type": "general_question",
            "instruction": "No business action required.",
            "action_type": "none",
            "target": "assistant",
            "action_instruction": "No business action required.",
        }
