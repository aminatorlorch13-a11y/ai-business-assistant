from dataclasses import dataclass


SUPPORTED_ACTIONS = frozenset(
    {
        "none",
        "create",
        "update",
        "delete",
    }
)


@dataclass(frozen=True)
class AssistantAction:
    """Immutable, validated action proposed by the assistant."""

    business_id: str
    action_type: str
    target: str
    instruction: str

    def __post_init__(self) -> None:
        self._validate_string(
            "business_id",
            self.business_id,
        )
        self._validate_string(
            "action_type",
            self.action_type,
        )
        self._validate_string(
            "target",
            self.target,
        )
        self._validate_string(
            "instruction",
            self.instruction,
        )

        if self.action_type not in SUPPORTED_ACTIONS:
            raise ValueError(
                "action_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_ACTIONS))}."
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
