"""Founder-facing safety operations boundary.

This module provides the Founder Operations layer with a controlled interface
to emergency safety state.

Important architectural rule:
Founder Operations never mutates safety persistence directly. All safety
mutations are delegated to SafetyControlService, which owns lifecycle
validation, atomic state changes, and platform audit events.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.founder.authorization import FounderAuthorizationService
from app.identity.models import AuthenticatedPrincipal
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import (
    SafetyControl,
    SafetyControlScope,
    SafetyIncident,
)
from app.safety.service import SafetyControlService


class FounderSafetyOperationsError(RuntimeError):
    """Raised when a Founder safety operation cannot be completed."""


@dataclass(frozen=True)
class FounderSafetyOperationsService:
    """Founder-only operational facade over the safety control service."""

    safety_repository: SQLiteSafetyRepository
    safety_service: SafetyControlService
    founder_authorization: FounderAuthorizationService

    MAX_CONTROLS = 100

    def __post_init__(self) -> None:
        if not isinstance(
            self.safety_repository,
            SQLiteSafetyRepository,
        ):
            raise TypeError(
                "safety_repository must be a SQLiteSafetyRepository."
            )

        if not isinstance(
            self.safety_service,
            SafetyControlService,
        ):
            raise TypeError(
                "safety_service must be a SafetyControlService."
            )

        if not isinstance(
            self.founder_authorization,
            FounderAuthorizationService,
        ):
            raise TypeError(
                "founder_authorization must be a FounderAuthorizationService."
            )

        if (
            self.safety_repository.database.path
            != self.safety_service.database.path
        ):
            raise ValueError(
                "Safety repository and safety service must use the same database."
            )

    def _require_founder(
        self,
        principal: AuthenticatedPrincipal,
    ) -> None:
        self.founder_authorization.require_founder(principal)

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must be a non-empty string."
            )
        return value.strip()

    @staticmethod
    def _validate_reason(reason: str) -> str:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string.")
        return reason.strip()

    @staticmethod
    def _validate_notes(notes: str) -> str:
        if not isinstance(notes, str) or not notes.strip():
            raise ValueError("notes must be a non-empty string.")
        return notes.strip()

    @classmethod
    def _validate_limit(cls, limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer.")
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if limit > cls.MAX_CONTROLS:
            raise ValueError(
                f"limit must not exceed {cls.MAX_CONTROLS}."
            )
        return limit

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_active_controls(
        self,
        principal: AuthenticatedPrincipal,
        *,
        limit: int = 100,
    ) -> tuple[SafetyControl, ...]:
        self._require_founder(principal)
        limit = self._validate_limit(limit)

        controls = self.safety_repository.list_active_controls(
            limit=limit,
        )

        if not isinstance(controls, (list, tuple)):
            raise FounderSafetyOperationsError(
                "Safety repository returned an invalid control collection."
            )

        result = tuple(controls)

        for control in result:
            if not isinstance(control, SafetyControl):
                raise FounderSafetyOperationsError(
                    "Safety repository returned an invalid safety control."
                )

        return result

    def get_control(
        self,
        principal: AuthenticatedPrincipal,
        control_id: str,
    ) -> SafetyControl | None:
        self._require_founder(principal)

        control_id = self._validate_id(
            control_id,
            "control_id",
        )

        control = self.safety_repository.get_control(control_id)

        if control is not None and not isinstance(control, SafetyControl):
            raise FounderSafetyOperationsError(
                "Safety repository returned an invalid safety control."
            )

        return control

    def get_incident(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident | None:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )

        incident = self.safety_repository.get_incident(incident_id)

        if incident is not None and not isinstance(
            incident,
            SafetyIncident,
        ):
            raise FounderSafetyOperationsError(
                "Safety repository returned an invalid safety incident."
            )

        return incident

    # ------------------------------------------------------------------
    # Mutation operations
    # ------------------------------------------------------------------

    def halt(
        self,
        principal: AuthenticatedPrincipal,
        *,
        scope: SafetyControlScope,
        target: str,
        reason: str,
        incident_id: str | None = None,
    ) -> SafetyControl:
        self._require_founder(principal)

        if not isinstance(scope, SafetyControlScope):
            raise TypeError(
                "scope must be a SafetyControlScope."
            )

        target = self._validate_id(target, "target")
        reason = self._validate_reason(reason)

        if incident_id is not None:
            incident_id = self._validate_id(
                incident_id,
                "incident_id",
            )

        return self.safety_service.halt(
            principal,
            scope=scope,
            target=target,
            reason=reason,
            incident_id=incident_id,
        )

    def begin_investigation(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )

        return self.safety_service.begin_investigation(
            principal,
            incident_id,
        )

    def resolve_incident(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
        *,
        notes: str,
    ) -> SafetyIncident:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )
        notes = self._validate_notes(notes)

        return self.safety_service.resolve_incident(
            principal,
            incident_id,
            notes=notes,
        )

    def verify_fix(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
        *,
        notes: str,
    ) -> SafetyIncident:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )
        notes = self._validate_notes(notes)

        return self.safety_service.verify_fix(
            principal,
            incident_id,
            notes=notes,
        )

    def authorize_resume(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )

        return self.safety_service.authorize_resume(
            principal,
            incident_id,
        )

    def resume_control(
        self,
        principal: AuthenticatedPrincipal,
        control_id: str,
    ) -> SafetyControl:
        self._require_founder(principal)

        control_id = self._validate_id(
            control_id,
            "control_id",
        )

        return self.safety_service.resume_control(
            principal,
            control_id,
        )

    def close_incident(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        self._require_founder(principal)

        incident_id = self._validate_id(
            incident_id,
            "incident_id",
        )

        return self.safety_service.close_incident(
            principal,
            incident_id,
        )
