from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FounderRecord:
    """Persistent platform-level Founder authority."""

    user_id: str
    active: bool

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("user_id must be a non-empty string.")

        if not isinstance(self.active, bool):
            raise TypeError("active must be a bool.")
