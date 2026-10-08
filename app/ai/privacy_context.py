from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrivacyContext:
    business_id: str
    conversation_text: str
    memory_text: str
    automation_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str) or not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        for name in (
            "conversation_text",
            "memory_text",
            "automation_text",
        ):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string.")
