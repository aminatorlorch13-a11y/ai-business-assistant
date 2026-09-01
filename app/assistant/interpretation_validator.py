from app.assistant.interpretation import AIInterpretation


ALLOWED_ACTIONS_BY_INTENT = {
    "general_question": frozenset({"none"}),
    "customer_request": frozenset({"none", "create", "update"}),
    "business_task": frozenset({"none", "create", "update", "delete"}),
}

ALLOWED_TARGETS_BY_ACTION = {
    "none": frozenset({"assistant", "appointment"}),
    "create": frozenset({"appointment"}),
    "update": frozenset({"appointment"}),
    "delete": frozenset({"appointment"}),
}


class AIInterpretationValidator:
    """Validates AI interpretations before they reach execution."""

    MAX_BUSINESS_ID_LENGTH = 128

    def validate(
        self,
        interpretation: AIInterpretation,
        business_id: str,
    ) -> AIInterpretation:
        """Enforce business isolation and semantic action constraints."""

        self._validate_business_id(business_id)

        if not isinstance(interpretation, AIInterpretation):
            raise TypeError(
                "interpretation must be an AIInterpretation."
            )

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

        allowed_actions = ALLOWED_ACTIONS_BY_INTENT.get(intent_type)

        if allowed_actions is None:
            raise ValueError(
                f"Unknown intent type: {intent_type}."
            )

        if action_type not in ALLOWED_TARGETS_BY_ACTION:
            raise ValueError(
                f"Unknown action type: {action_type}."
            )

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

    @classmethod
    def _validate_business_id(
        cls,
        business_id: object,
    ) -> None:
        if not isinstance(business_id, str):
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if len(business_id) > cls.MAX_BUSINESS_ID_LENGTH:
            raise ValueError(
                "business_id exceeds the maximum allowed length."
            )
