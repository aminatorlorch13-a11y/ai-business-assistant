from app.assistant.interpretation import AIInterpretation


ALLOWED_ACTIONS_BY_INTENT = {
    "general_question": {"none"},
    "customer_request": {"none", "create", "update"},
    "business_task": {"none", "create", "update", "delete"},
}


SUPPORTED_TARGETS = {
    "appointment",
    "assistant",
}


ALLOWED_TARGETS_BY_ACTION = {
    "none": {"assistant", "appointment"},
    "create": {"appointment"},
    "update": {"appointment"},
    "delete": {"appointment"},
}


class AIInterpretationValidator:
    """Validates AI interpretations before they reach the execution layer."""

    def validate(
        self,
        interpretation: AIInterpretation,
        business_id: str,
    ) -> AIInterpretation:
        """Validate an AI interpretation against the active business."""

        if interpretation.intent.business_id != business_id:
            raise ValueError(
                "AI interpretation intent does not belong to this business."
            )

        if interpretation.action.business_id != business_id:
            raise ValueError(
                "AI interpretation action does not belong to this business."
            )

        intent_type = interpretation.intent.intent_type
        action_type = interpretation.action.action_type
        target = interpretation.action.target

        if intent_type not in ALLOWED_ACTIONS_BY_INTENT:
            raise ValueError(
                f"Unknown intent type: {intent_type}."
            )

        if action_type not in ALLOWED_TARGETS_BY_ACTION:
            raise ValueError(
                f"Unknown action type: {action_type}."
            )

        if target not in SUPPORTED_TARGETS:
            raise ValueError(
                f"Unsupported action target: {target}"
            )

        allowed_actions = ALLOWED_ACTIONS_BY_INTENT[intent_type]

        if action_type not in allowed_actions:
            raise ValueError(
                f"Action '{action_type}' is not valid "
                f"for intent '{intent_type}'."
            )

        allowed_targets = ALLOWED_TARGETS_BY_ACTION[action_type]

        if target not in allowed_targets:
            raise ValueError(
                f"Target '{target}' is not valid "
                f"for action '{action_type}'."
            )

        return interpretation
