"""Immutable, tenant-scoped specification for an approved Forge task."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.forge.languages import get_language


@dataclass(frozen=True)
class ForgeTaskSpec:
    business_id: str
    project_id: str
    job_id: str
    instructions: str
    scope: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    language: str = "python"

    MAX_INSTRUCTIONS_LENGTH = 20_000
    MAX_SCOPE_ITEMS = 32
    MAX_SCOPE_ITEM_LENGTH = 1_024
    MAX_ACCEPTANCE_ITEMS = 32
    MAX_ACCEPTANCE_ITEM_LENGTH = 1_024
    MAX_SERIALIZED_BYTES = 32_768

    def __post_init__(self) -> None:
        language = get_language(self.language)
        object.__setattr__(self, "language", language.language_id)

        for name in ("business_id", "project_id", "job_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
            if len(value) > 128 or value != value.strip():
                raise ValueError(f"{name} is invalid.")

        if not isinstance(self.instructions, str):
            raise TypeError("instructions must be a string.")
        if not self.instructions.strip():
            raise ValueError("instructions must not be empty.")
        if len(self.instructions) > self.MAX_INSTRUCTIONS_LENGTH:
            raise ValueError("instructions exceed the maximum length.")

        self._validate_items(
            "scope", self.scope, self.MAX_SCOPE_ITEMS,
            self.MAX_SCOPE_ITEM_LENGTH,
        )
        self._validate_items(
            "acceptance_criteria",
            self.acceptance_criteria,
            self.MAX_ACCEPTANCE_ITEMS,
            self.MAX_ACCEPTANCE_ITEM_LENGTH,
        )
        if not self.acceptance_criteria:
            raise ValueError("At least one acceptance criterion is required.")

        if len(self.to_json().encode("utf-8")) > self.MAX_SERIALIZED_BYTES:
            raise ValueError("Task specification exceeds the maximum size.")

    @staticmethod
    def _validate_items(
        name: str,
        values: tuple[str, ...],
        max_items: int,
        max_length: int,
    ) -> None:
        if not isinstance(values, tuple):
            raise TypeError(f"{name} must be a tuple of strings.")
        if len(values) > max_items:
            raise ValueError(f"{name} contains too many items.")
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Every {name} item must be non-empty.")
            if len(value) > max_length:
                raise ValueError(f"A {name} item exceeds the maximum length.")

    def to_dict(self) -> dict[str, object]:
        return {
            "business_id": self.business_id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "instructions": self.instructions,
            "scope": list(self.scope),
            "acceptance_criteria": list(self.acceptance_criteria),
            **({"language": self.language} if self.language != "python" else {}),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, value: str) -> "ForgeTaskSpec":
        try:
            data = json.loads(value)
            if not isinstance(data, dict):
                raise ValueError("Task specification must be a JSON object.")
            return cls(
                business_id=data["business_id"],
                project_id=data["project_id"],
                job_id=data["job_id"],
                instructions=data["instructions"],
                scope=tuple(data["scope"]),
                acceptance_criteria=tuple(data["acceptance_criteria"]),
                language=data.get("language", "python"),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Stored Forge task specification is invalid.") from exc
