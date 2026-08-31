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

        if interpretation.action.target not in SUPPORTED_TARGETS:
            raise ValueError(
                f"Unsupported action target: "
                f"{interpretation.action.target}"
            )

        allowed_actions = ALLOWED_ACTIONS_BY_INTENT[
            interpretation.intent.intent_type
        ]

        if interpretation.action.action_type not in allowed_actions:
            raise ValueError(
                f"Action '{interpretation.action.action_type}' is not valid "
                f"for intent '{interpretation.intent.intent_type}'."
            )

        allowed_targets = ALLOWED_TARGETS_BY_ACTION[
            interpretation.action.action_type
        ]

        if interpretation.action.target not in allowed_targets:
            raise ValueError(
                f"Target '{interpretation.action.target}' is not valid "
                f"for action '{interpretation.action.action_type}'."
            )

        return interpretation
