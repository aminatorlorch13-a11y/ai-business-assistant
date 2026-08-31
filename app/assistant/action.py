from dataclasses import dataclass


SUPPORTED_ACTIONS = {
    "none",
    "create",
    "update",
    "delete",
}


@dataclass(frozen=True)
class AssistantAction:
    """A structured action proposed by the assistant."""

    business_id: str
    action_type: str
    target: str
    instruction: str

    def __post_init__(self) -> None:
        fields = {
            "business_id": self.business_id,
            "target": self.target,
            "instruction": self.instruction,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if self.action_type not in SUPPORTED_ACTIONS:
            raise ValueError(
                f"action_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_ACTIONS))}."
            )
