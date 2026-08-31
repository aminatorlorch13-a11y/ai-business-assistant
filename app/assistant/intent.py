from dataclasses import dataclass


SUPPORTED_INTENTS = {
    "general_question",
    "customer_request",
    "business_task",
}


@dataclass(frozen=True)
class AssistantIntent:
    """A structured interpretation of an incoming assistant message."""

    business_id: str
    intent_type: str
    instruction: str

    def __post_init__(self) -> None:
        fields = {
            "business_id": self.business_id,
            "instruction": self.instruction,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if self.intent_type not in SUPPORTED_INTENTS:
            raise ValueError(
                f"intent_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_INTENTS))}."
            )
