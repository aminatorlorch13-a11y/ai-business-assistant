from dataclasses import dataclass
from enum import Enum


class Capability(str, Enum):
    """
    High-level capabilities available to the business assistant.

    Capabilities describe WHAT the assistant wants to do.
    They do not describe HOW or WHERE the operation is performed.
    """

    CONVERSATION = "conversation"
    TIME = "time"
    MEMORY = "memory"
    RESEARCH = "research"
    AUTOMATION = "automation"
    COMMUNICATION = "communication"
    VOICE = "voice"


@dataclass(frozen=True)
class CapabilityDecision:
    """
    Immutable classification result for an assistant request.

    This describes the capability identified by classification and whether
    the request requires authorization. It does not grant authorization.
    """

    capability: Capability
    requires_authorization: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.requires_authorization, bool):
            raise TypeError(
                "requires_authorization must be a boolean."
            )

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string.")

        if not self.reason.strip():
            raise ValueError(
                "reason must be a non-empty string."
            )


@dataclass(frozen=True)
class CapabilityResult:
    """
    Immutable result returned by a capability handler.

    A result describes the outcome of capability execution.
    It does not grant authorization and does not perform another action.
    """

    capability: Capability
    business_id: str
    success: bool
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.success, bool):
            raise TypeError("success must be a boolean.")

        if not isinstance(self.message, str):
            raise TypeError("message must be a string.")

        if not self.message.strip():
            raise ValueError(
                "message must be a non-empty string."
            )


@dataclass(frozen=True)
class CapabilityRequest:
    """
    Immutable request to execute a high-level assistant capability.
    """

    capability: Capability
    business_id: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise TypeError("capability must be a Capability.")

        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string.")

        if not self.reason.strip():
            raise ValueError(
                "reason must be a non-empty string."
            )
