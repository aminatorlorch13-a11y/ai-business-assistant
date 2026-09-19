from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.assistant.capability import Capability


@dataclass(frozen=True)
class AICapabilityRequest:
    """
    Structured capability request proposed by the AI layer.

    This is an untrusted AI proposal, not an authorization grant and not
    an executable instruction.

    The AI may identify:
      - which high-level capability it wants,
      - which registered operation it wants,
      - the operation arguments,
      - why the operation is being requested,
      - whether the proposed operation is considered reversible.

    Business identity, channel, integration, authorization, safety, and
    execution are supplied and enforced by the application layer.
    """

    capability: Capability
    operation: str
    arguments: Mapping[str, Any]
    reason: str
    reversible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.operation, str):
            raise TypeError("operation must be a string.")
        if not self.operation.strip():
            raise ValueError("operation must be a non-empty string.")

        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping.")

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string.")
        if not self.reason.strip():
            raise ValueError("reason must be a non-empty string.")

        if not isinstance(self.reversible, bool):
            raise TypeError("reversible must be a boolean.")

        object.__setattr__(self, "operation", self.operation.strip())
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(dict(self.arguments)),
        )
        object.__setattr__(self, "reason", self.reason.strip())
