from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SafetyControlScope(str, Enum):
    GLOBAL = "global"
    BUSINESS = "business"
    CAPABILITY = "capability"
    CHANNEL = "channel"
    INTEGRATION = "integration"


class SafetyControlState(str, Enum):
    ACTIVE = "active"
    HALTED = "halted"


class SafetyIncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    VERIFIED = "verified"
    RESUME_AUTHORIZED = "resume_authorized"
    CLOSED = "closed"


def _validate_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    if len(value) > 128:
        raise ValueError(f"{field_name} exceeds the maximum allowed length.")


def _validate_datetime(value: object, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


@dataclass(frozen=True)
class SafetyIncident:
    incident_id: str
    status: SafetyIncidentStatus
    reason: str
    created_at: datetime
    created_by_user_id: str
    resolved_at: datetime | None = None
    resolved_by_user_id: str | None = None
    verification_notes: str | None = None
    verified_at: datetime | None = None
    verified_by_user_id: str | None = None
    resume_authorized_at: datetime | None = None
    resume_authorized_by_user_id: str | None = None
    closed_at: datetime | None = None
    closed_by_user_id: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.incident_id, "incident_id")

        if not isinstance(self.status, SafetyIncidentStatus):
            raise TypeError("status must be a SafetyIncidentStatus.")

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string.")

        if len(self.reason) > 4096:
            raise ValueError("reason exceeds the maximum allowed length.")

        _validate_datetime(self.created_at, "created_at")
        _validate_id(self.created_by_user_id, "created_by_user_id")

        self._validate_transition_evidence()

    def _validate_transition_evidence(self) -> None:
        if self.status in {
            SafetyIncidentStatus.RESOLVED,
            SafetyIncidentStatus.VERIFIED,
            SafetyIncidentStatus.RESUME_AUTHORIZED,
            SafetyIncidentStatus.CLOSED,
        }:
            if self.resolved_at is None or self.resolved_by_user_id is None:
                raise ValueError(
                    "resolved status requires resolution evidence."
                )

        if self.status in {
            SafetyIncidentStatus.VERIFIED,
            SafetyIncidentStatus.RESUME_AUTHORIZED,
            SafetyIncidentStatus.CLOSED,
        }:
            if self.verified_at is None or self.verified_by_user_id is None:
                raise ValueError(
                    "verified status requires verification evidence."
                )

        if self.status in {
            SafetyIncidentStatus.RESUME_AUTHORIZED,
            SafetyIncidentStatus.CLOSED,
        }:
            if (
                self.resume_authorized_at is None
                or self.resume_authorized_by_user_id is None
            ):
                raise ValueError(
                    "resume-authorized status requires resume authorization evidence."
                )

        if self.status is SafetyIncidentStatus.CLOSED:
            if self.closed_at is None or self.closed_by_user_id is None:
                raise ValueError(
                    "closed status requires closure evidence."
                )

        for field_name, value in (
            ("resolved_by_user_id", self.resolved_by_user_id),
            ("verified_by_user_id", self.verified_by_user_id),
            (
                "resume_authorized_by_user_id",
                self.resume_authorized_by_user_id,
            ),
            ("closed_by_user_id", self.closed_by_user_id),
        ):
            if value is not None:
                _validate_id(value, field_name)

        for field_name, value in (
            ("resolved_at", self.resolved_at),
            ("verified_at", self.verified_at),
            ("resume_authorized_at", self.resume_authorized_at),
            ("closed_at", self.closed_at),
        ):
            if value is not None:
                _validate_datetime(value, field_name)

        if self.verification_notes is not None:
            if (
                not isinstance(self.verification_notes, str)
                or not self.verification_notes.strip()
            ):
                raise ValueError(
                    "verification_notes must be non-empty when provided."
                )
            if len(self.verification_notes) > 8192:
                raise ValueError(
                    "verification_notes exceeds the maximum allowed length."
                )


@dataclass(frozen=True)
class SafetyControl:
    control_id: str
    scope: SafetyControlScope
    target: str
    state: SafetyControlState
    reason: str
    activated_at: datetime
    activated_by_user_id: str
    incident_id: str
    resolved_at: datetime | None = None
    resolved_by_user_id: str | None = None
    resumed_at: datetime | None = None
    resumed_by_user_id: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.control_id, "control_id")

        if not isinstance(self.scope, SafetyControlScope):
            raise TypeError("scope must be a SafetyControlScope.")

        _validate_id(self.target, "target")

        if not isinstance(self.state, SafetyControlState):
            raise TypeError("state must be a SafetyControlState.")

        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string.")

        if len(self.reason) > 4096:
            raise ValueError("reason exceeds the maximum allowed length.")

        _validate_datetime(self.activated_at, "activated_at")
        _validate_id(self.activated_by_user_id, "activated_by_user_id")
        _validate_id(self.incident_id, "incident_id")

        if self.state is SafetyControlState.ACTIVE:
            if self.resolved_at is None or self.resolved_by_user_id is None:
                raise ValueError(
                    "active control requires resolution evidence."
                )
            if self.resumed_at is None or self.resumed_by_user_id is None:
                raise ValueError(
                    "active control requires resume evidence."
                )

        for field_name, value in (
            ("resolved_by_user_id", self.resolved_by_user_id),
            ("resumed_by_user_id", self.resumed_by_user_id),
        ):
            if value is not None:
                _validate_id(value, field_name)

        for field_name, value in (
            ("resolved_at", self.resolved_at),
            ("resumed_at", self.resumed_at),
        ):
            if value is not None:
                _validate_datetime(value, field_name)
