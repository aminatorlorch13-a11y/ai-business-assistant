from dataclasses import dataclass


SUPPORTED_INTENTS = frozenset(
    {
        "general_question",
        "customer_request",
        "business_task",
    }
)


@dataclass(frozen=True)
class AssistantIntent:
    """Immutable, validated intent produced by the assistant."""

    business_id: str
    intent_type: str
    instruction: str

    def __post_init__(self) -> None:
        self._validate_string(
            "business_id",
            self.business_id,
        )
        self._validate_string(
            "intent_type",
            self.intent_type,
        )
        self._validate_string(
            "instruction",
            self.instruction,
        )

        if self.intent_type not in SUPPORTED_INTENTS:
            raise ValueError(
                "intent_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_INTENTS))}."
            )

    @staticmethod
    def _validate_string(
        field_name: str,
        value: object,
    ) -> None:
        """Validate a required string field."""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must be a non-empty string."
            )
