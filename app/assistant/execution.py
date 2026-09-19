from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.assistant.capability import Capability


@dataclass(frozen=True)
class CapabilityExecutionRequest:
    """Validated request for one concrete operation of a capability."""

    capability: Capability
    operation: str
    business_id: str
    arguments: Mapping[str, Any]
    reason: str
    channel: str | None = None
    integration: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.operation, str):
            raise TypeError("operation must be a string.")
        if not self.operation.strip():
            raise ValueError("operation must be a non-empty string.")

        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")
        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping.")

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string.")
        if not self.reason.strip():
            raise ValueError("reason must be a non-empty string.")

        for name, value in (
            ("channel", self.channel),
            ("integration", self.integration),
        ):
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be a string or None.")
                if not value.strip():
                    raise ValueError(
                        f"{name} must be a non-empty string when provided."
                    )

        object.__setattr__(
            self,
            "operation",
            self.operation.strip(),
        )
        object.__setattr__(
            self,
            "business_id",
            self.business_id.strip(),
        )
        object.__setattr__(
            self,
            "reason",
            self.reason.strip(),
        )
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(dict(self.arguments)),
        )

        if self.channel is not None:
            object.__setattr__(self, "channel", self.channel.strip())

        if self.integration is not None:
            object.__setattr__(
                self,
                "integration",
                self.integration.strip(),
            )


@dataclass(frozen=True)
class CapabilityExecutionResult:
    """Verified application result from a concrete capability operation."""

    success: bool
    capability: Capability
    operation: str
    business_id: str
    data: Any = None
    provider_reference: str | None = None
    verification: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.operation, str):
            raise TypeError("operation must be a string.")
        if not self.operation.strip():
            raise ValueError("operation must be a non-empty string.")

        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")
        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        for name, value in (
            ("provider_reference", self.provider_reference),
            ("verification", self.verification),
            ("error", self.error),
        ):
            if value is not None:
                if not isinstance(value, str):
                    raise TypeError(f"{name} must be a string or None.")
                if not value.strip():
                    raise ValueError(
                        f"{name} must be a non-empty string when provided."
                    )

        object.__setattr__(
            self,
            "operation",
            self.operation.strip(),
        )
        object.__setattr__(
            self,
            "business_id",
            self.business_id.strip(),
        )

        if self.success and self.error is not None:
            raise ValueError("successful results cannot contain an error.")

        if not self.success and self.error is None:
            raise ValueError("failed results must contain an error.")

        for name in ("provider_reference", "verification", "error"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, value.strip())
