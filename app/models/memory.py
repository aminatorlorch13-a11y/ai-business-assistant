from dataclasses import dataclass


SUPPORTED_MEMORY_TYPES = {
    "business_preference",
    "business_rule",
    "customer_preference",
    "operational_fact",
}


@dataclass(frozen=True)
class Memory:
    """Represents a piece of persistent business memory."""

    memory_id: str
    business_id: str
    content: str
    memory_type: str
    importance: int

    def __post_init__(self) -> None:
        fields = {
            "memory_id": self.memory_id,
            "business_id": self.business_id,
            "content": self.content,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")

        if self.memory_type not in SUPPORTED_MEMORY_TYPES:
            raise ValueError(
                f"memory_type must be one of: "
                f"{', '.join(sorted(SUPPORTED_MEMORY_TYPES))}."
            )

        if not isinstance(self.importance, int):
            raise ValueError("importance must be an integer.")

        if not 1 <= self.importance <= 5:
            raise ValueError("importance must be between 1 and 5.")
