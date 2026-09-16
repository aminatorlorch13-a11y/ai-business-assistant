from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.founder.authorization import FounderAuthorizationService
from app.identity.models import AuthenticatedPrincipal
from app.persistence.platform_event_repository import (
    SQLitePlatformEventRepository,
)
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.persistence.safety_transaction import SQLiteSafetyTransaction
from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)
from app.safety.models import (
    SafetyControl,
    SafetyControlScope,
    SafetyControlState,
    SafetyIncident,
    SafetyIncidentStatus,
)


class SafetyControlError(RuntimeError):
    """Base error for emergency safety control operations."""


class SafetyControlService:
    """
    Founder-authorized emergency safety control plane.

    This service is deliberately outside the AI reasoning path.
    """

    def __init__(
        self,
        safety_repository: SQLiteSafetyRepository,
        founder_authorization: FounderAuthorizationService,
        platform_events: SQLitePlatformEventRepository,
    ) -> None:
        if not isinstance(safety_repository, SQLiteSafetyRepository):
            raise TypeError(
                "safety_repository must be a SQLiteSafetyRepository."
            )
        if not isinstance(
            founder_authorization,
            FounderAuthorizationService,
        ):
            raise TypeError(
                "founder_authorization must be a "
                "FounderAuthorizationService."
            )
        if not isinstance(
            platform_events,
            SQLitePlatformEventRepository,
        ):
            raise TypeError(
                "platform_events must be a "
                "SQLitePlatformEventRepository."
            )

        if safety_repository.database.path != platform_events.database.path:
            raise ValueError(
                "Safety and platform event repositories must use the same database."
            )

        self._safety = safety_repository
        self._founders = founder_authorization
        self._events = platform_events
        self._database = safety_repository.database

    def halt(
        self,
        principal: AuthenticatedPrincipal,
        *,
        scope: SafetyControlScope,
        target: str,
        reason: str,
        incident_id: str | None = None,
    ) -> SafetyControl:
        founder = self._founders.require_founder(principal)

        if not isinstance(scope, SafetyControlScope):
            raise TypeError("scope must be a SafetyControlScope.")

        self._validate_text(target, "target")
        self._validate_text(reason, "reason")

        existing = self._safety.get_active_control(scope, target)
        if existing is not None:
            raise SafetyControlError(
                "A safety halt is already active for this scope and target."
            )

        now = datetime.now(timezone.utc)

        transaction = self._transaction()

        try:
            if incident_id is None:
                incident = SafetyIncident(
                    incident_id=f"incident-{uuid4().hex}",
                    status=SafetyIncidentStatus.OPEN,
                    reason=reason,
                    created_at=now,
                    created_by_user_id=founder.user_id,
                )
                transaction.create_incident(incident)
            else:
                incident = self._safety.get_incident(incident_id)

                if incident is None:
                    raise SafetyControlError("Safety incident not found.")


                if incident.status is not SafetyIncidentStatus.OPEN:
                    raise SafetyControlError(
                        "Only an open incident can activate a new halt."
                    )

            control = SafetyControl(
                control_id=f"control-{uuid4().hex}",
                scope=scope,
                target=target,
                state=SafetyControlState.HALTED,
                reason=reason,
                activated_at=now,
                activated_by_user_id=founder.user_id,
                incident_id=incident.incident_id,
            )

            transaction.create_control(control)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.halt",
                outcome=PlatformEventOutcome.SUCCESS,
                business_id=(
                    target
                    if scope is SafetyControlScope.BUSINESS
                    else None
                ),
                metadata={
                    "control_id": control.control_id,
                    "scope": scope.value,
                    "target": target,
                    "incident_id": incident.incident_id,
                },
            )

            transaction.commit()
            return control

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def begin_investigation(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        founder = self._founders.require_founder(principal)
        incident = self._require_incident(incident_id)


        if incident.status is not SafetyIncidentStatus.OPEN:
            raise SafetyControlError(
                "Only an open incident can enter investigation."
            )

        updated = SafetyIncident(
            incident_id=incident.incident_id,
            status=SafetyIncidentStatus.INVESTIGATING,
            reason=incident.reason,
            created_at=incident.created_at,
            created_by_user_id=incident.created_by_user_id,
        )

        transaction = self._transaction()

        try:
            transaction.save_incident(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.investigation_started",
                outcome=PlatformEventOutcome.SUCCESS,
                metadata={"incident_id": incident_id},
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def resolve_incident(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
        *,
        notes: str,
    ) -> SafetyIncident:
        founder = self._founders.require_founder(principal)
        incident = self._require_incident(incident_id)


        if incident.status is not SafetyIncidentStatus.INVESTIGATING:
            raise SafetyControlError(
                "Only an investigated incident can be resolved."
            )

        self._validate_text(notes, "notes")

        now = datetime.now(timezone.utc)

        updated = SafetyIncident(
            incident_id=incident.incident_id,
            status=SafetyIncidentStatus.RESOLVED,
            reason=incident.reason,
            created_at=incident.created_at,
            created_by_user_id=incident.created_by_user_id,
            resolved_at=now,
            resolved_by_user_id=founder.user_id,
            verification_notes=notes,
        )

        transaction = self._transaction()

        try:
            transaction.save_incident(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.incident_resolved",
                outcome=PlatformEventOutcome.SUCCESS,
                metadata={
                    "incident_id": incident_id,
                    "notes_length": len(notes),
                },
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def verify_fix(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
        *,
        notes: str,
    ) -> SafetyIncident:
        founder = self._founders.require_founder(principal)
        incident = self._require_incident(incident_id)


        if incident.status is not SafetyIncidentStatus.RESOLVED:
            raise SafetyControlError(
                "Only a resolved incident can be verified."
            )

        self._validate_text(notes, "notes")

        now = datetime.now(timezone.utc)

        updated = SafetyIncident(
            incident_id=incident.incident_id,
            status=SafetyIncidentStatus.VERIFIED,
            reason=incident.reason,
            created_at=incident.created_at,
            created_by_user_id=incident.created_by_user_id,
            resolved_at=incident.resolved_at,
            resolved_by_user_id=incident.resolved_by_user_id,
            verification_notes=notes,
            verified_at=now,
            verified_by_user_id=founder.user_id,
        )

        transaction = self._transaction()

        try:
            transaction.save_incident(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.fix_verified",
                outcome=PlatformEventOutcome.SUCCESS,
                metadata={"incident_id": incident_id},
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def authorize_resume(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        founder = self._founders.require_founder(principal)
        incident = self._require_incident(incident_id)


        if incident.status is not SafetyIncidentStatus.VERIFIED:
            raise SafetyControlError(
                "Only a verified incident can authorize resume."
            )

        now = datetime.now(timezone.utc)

        updated = SafetyIncident(
            incident_id=incident.incident_id,
            status=SafetyIncidentStatus.RESUME_AUTHORIZED,
            reason=incident.reason,
            created_at=incident.created_at,
            created_by_user_id=incident.created_by_user_id,
            resolved_at=incident.resolved_at,
            resolved_by_user_id=incident.resolved_by_user_id,
            verification_notes=incident.verification_notes,
            verified_at=incident.verified_at,
            verified_by_user_id=incident.verified_by_user_id,
            resume_authorized_at=now,
            resume_authorized_by_user_id=founder.user_id,
        )

        transaction = self._transaction()

        try:
            transaction.save_incident(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.resume_authorized",
                outcome=PlatformEventOutcome.SUCCESS,
                metadata={"incident_id": incident_id},
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def resume_control(
        self,
        principal: AuthenticatedPrincipal,
        control_id: str,
    ) -> SafetyControl:
        founder = self._founders.require_founder(principal)
        control = self._safety.get_control(control_id)

        if control is None:
            raise SafetyControlError("Safety control not found.")

        if control.state is not SafetyControlState.HALTED:
            raise SafetyControlError(
                "Only a halted safety control can be resumed."
            )


        incident = self._require_incident(control.incident_id)

        if incident.status is not SafetyIncidentStatus.RESUME_AUTHORIZED:
            raise SafetyControlError(
                "Incident is not authorized for resume."
            )

        now = datetime.now(timezone.utc)

        updated = SafetyControl(
            control_id=control.control_id,
            scope=control.scope,
            target=control.target,
            state=SafetyControlState.ACTIVE,
            reason=control.reason,
            activated_at=control.activated_at,
            activated_by_user_id=control.activated_by_user_id,
            incident_id=control.incident_id,
            resolved_at=incident.resolved_at,
            resolved_by_user_id=incident.resolved_by_user_id,
            resumed_at=now,
            resumed_by_user_id=founder.user_id,
        )

        transaction = self._transaction()

        try:
            transaction.save_control(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.control_resumed",
                outcome=PlatformEventOutcome.SUCCESS,
                business_id=(
                    control.target
                    if control.scope is SafetyControlScope.BUSINESS
                    else None
                ),
                metadata={
                    "control_id": control.control_id,
                    "scope": control.scope.value,
                    "target": control.target,
                    "incident_id": control.incident_id,
                },
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    def close_incident(
        self,
        principal: AuthenticatedPrincipal,
        incident_id: str,
    ) -> SafetyIncident:
        founder = self._founders.require_founder(principal)
        incident = self._require_incident(incident_id)


        if incident.status is not SafetyIncidentStatus.RESUME_AUTHORIZED:
            raise SafetyControlError(
                "Only a resume-authorized incident can be closed."
            )

        now = datetime.now(timezone.utc)

        updated = SafetyIncident(
            incident_id=incident.incident_id,
            status=SafetyIncidentStatus.CLOSED,
            reason=incident.reason,
            created_at=incident.created_at,
            created_by_user_id=incident.created_by_user_id,
            resolved_at=incident.resolved_at,
            resolved_by_user_id=incident.resolved_by_user_id,
            verification_notes=incident.verification_notes,
            verified_at=incident.verified_at,
            verified_by_user_id=incident.verified_by_user_id,
            resume_authorized_at=incident.resume_authorized_at,
            resume_authorized_by_user_id=incident.resume_authorized_by_user_id,
            closed_at=now,
            closed_by_user_id=founder.user_id,
        )

        transaction = self._transaction()

        try:
            transaction.save_incident(updated)

            self._append_event(
                transaction=transaction,
                principal=principal,
                action="safety.incident_closed",
                outcome=PlatformEventOutcome.SUCCESS,
                metadata={"incident_id": incident_id},
            )

            transaction.commit()
            return updated

        except Exception:
            try:
                transaction.rollback()
            except RuntimeError:
                pass
            raise

    @property
    def database(self) -> SQLiteDatabase:
        return self._database

    def _transaction(self) -> SQLiteSafetyTransaction:
        return SQLiteSafetyTransaction(self._database)

    @staticmethod
    def _commit_or_rollback(transaction: SQLiteSafetyTransaction) -> None:
        try:
            transaction.commit()
        except Exception:
            try:
                transaction.rollback()
            except Exception:
                pass
            raise

    def _require_incident(self, incident_id: str) -> SafetyIncident:
        incident = self._safety.get_incident(incident_id)
        if incident is None:
            raise SafetyControlError("Safety incident not found.")
        return incident

    def _append_event(
        self,
        *,
        transaction: SQLiteSafetyTransaction,
        principal: AuthenticatedPrincipal,
        action: str,
        outcome: PlatformEventOutcome,
        metadata: dict[str, object],
        business_id: str | None = None,
    ) -> None:
        event = PlatformEvent(
            event_id=f"event-{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            event_type="safety_control",
            business_id=business_id,
            user_id=principal.user_id,
            channel=PlatformEventChannel.FOUNDER,
            actor_type=PlatformEventActorType.FOUNDER,
            action=action,
            outcome=outcome,
            correlation_id=f"safety-{uuid4().hex}",
            metadata=metadata,
        )
        transaction.append_event(event)

    @staticmethod
    def _validate_text(value: object, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string.")
        if len(value) > 4096:
            raise ValueError(
                f"{field_name} exceeds the maximum allowed length."
            )
