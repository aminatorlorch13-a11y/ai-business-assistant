from collections.abc import Mapping

from app.assistant.action import AssistantAction
from app.assistant.intent import AssistantIntent
from app.assistant.interpretation import AIInterpretation


ALLOWED_INTENTS = {
    "general_question",
    "customer_request",
    "business_task",
}

ALLOWED_ACTIONS = {
    "none",
    "create",
    "update",
    "delete",
}


class AIResponseParser:
    """Converts structured AI output into a validated assistant interpretation."""

    REQUIRED_FIELDS = {
        "intent_type",
        "instruction",
        "action_type",
        "target",
        "action_instruction",
    }

    def parse(
        self,
        data: Mapping[str, object],
        business_id: str,
    ) -> AIInterpretation:
        """Parse structured AI output for one specific business."""

        if not isinstance(data, Mapping):
            raise ValueError("AI response must be a mapping.")

        missing = self.REQUIRED_FIELDS - data.keys()

        if missing:
            raise ValueError(
                f"AI response is missing required fields: {sorted(missing)}."
            )

        intent_type = data["intent_type"]
        instruction = data["instruction"]
        action_type = data["action_type"]
        target = data["target"]
        action_instruction = data["action_instruction"]

        supplied_business_id = data.get("business_id")

        if supplied_business_id is not None and supplied_business_id != business_id:
            raise ValueError(
                "AI response business_id does not belong to this business."
            )

        if intent_type not in ALLOWED_INTENTS:
            raise ValueError(
                f"Unknown intent type: {intent_type}."
            )

        if action_type not in ALLOWED_ACTIONS:
            raise ValueError(
                f"Unknown action type: {action_type}."
            )

        if not all(
            isinstance(value, str)
            for value in (
                intent_type,
                instruction,
                action_type,
                target,
                action_instruction,
            )
        ):
            raise ValueError("AI response fields must contain strings.")

        return AIInterpretation(
            intent=AssistantIntent(
                business_id=business_id,
                intent_type=intent_type,
                instruction=instruction,
            ),
            action=AssistantAction(
                business_id=business_id,
                action_type=action_type,
                target=target,
                instruction=action_instruction,
            ),
        )
