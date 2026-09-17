from __future__ import annotations

from datetime import datetime

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_from_storage
from app.safety.models import (
    SafetyControl,
    SafetyControlScope,
    SafetyControlState,
    SafetyIncident,
    SafetyIncidentStatus,
)


class SQLiteSafetyRepository:
    """Durable repository for emergency safety controls and incidents."""

    MAX_LIST_LIMIT = 500

    @property
    def database(self) -> SQLiteDatabase:
        return self._database

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create_incident(self, incident: SafetyIncident) -> SafetyIncident:
        if not isinstance(incident, SafetyIncident):
            raise TypeError("incident must be a SafetyIncident.")

        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO safety_incidents(
                    incident_id,
                    status,
                    reason,
                    created_at,
                    created_by_user_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.status.value,
                    incident.reason,
                    incident.created_at.isoformat(),
                    incident.created_by_user_id,
                ),
            )

        return incident

    def get_incident(self, incident_id: str) -> SafetyIncident | None:
        self._validate_id(incident_id, "incident_id")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    incident_id,
                    status,
                    reason,
                    created_at,
                    created_by_user_id,
                    resolved_at,
                    resolved_by_user_id,
                    verification_notes,
                    verified_at,
                    verified_by_user_id,
                    resume_authorized_at,
                    resume_authorized_by_user_id,
                    closed_at,
                    closed_by_user_id
                FROM safety_incidents
                WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()

        return self._incident_from_row(row) if row else None

    def save_incident(self, incident: SafetyIncident) -> SafetyIncident:
        if not isinstance(incident, SafetyIncident):
            raise TypeError("incident must be a SafetyIncident.")

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE safety_incidents
                SET
                    status = ?,
                    reason = ?,
                    resolved_at = ?,
                    resolved_by_user_id = ?,
                    verification_notes = ?,
                    verified_at = ?,
                    verified_by_user_id = ?,
                    resume_authorized_at = ?,
                    resume_authorized_by_user_id = ?,
                    closed_at = ?,
                    closed_by_user_id = ?
                WHERE incident_id = ?
                """,
                (
                    incident.status.value,
                    incident.reason,
                    self._dt(incident.resolved_at),
                    incident.resolved_by_user_id,
                    incident.verification_notes,
                    self._dt(incident.verified_at),
                    incident.verified_by_user_id,
                    self._dt(incident.resume_authorized_at),
                    incident.resume_authorized_by_user_id,
                    self._dt(incident.closed_at),
                    incident.closed_by_user_id,
                    incident.incident_id,
                ),
            )

            if cursor.rowcount == 0:
                raise LookupError("Safety incident not found.")

        return incident

    def create_control(self, control: SafetyControl) -> SafetyControl:
        if not isinstance(control, SafetyControl):
            raise TypeError("control must be a SafetyControl.")

        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO safety_controls(
                    control_id,
                    scope,
                    target,
                    state,
                    reason,
                    activated_at,
                    activated_by_user_id,
                    incident_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    control.control_id,
                    control.scope.value,
                    control.target,
                    control.state.value,
                    control.reason,
                    control.activated_at.isoformat(),
                    control.activated_by_user_id,
                    control.incident_id,
                ),
            )

        return control

    def get_control(self, control_id: str) -> SafetyControl | None:
        self._validate_id(control_id, "control_id")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    control_id,
                    scope,
                    target,
                    state,
                    reason,
                    activated_at,
                    activated_by_user_id,
                    incident_id,
                    resolved_at,
                    resolved_by_user_id,
                    resumed_at,
                    resumed_by_user_id
                FROM safety_controls
                WHERE control_id = ?
                """,
                (control_id,),
            ).fetchone()

        return self._control_from_row(row) if row else None

    def get_active_control(
        self,
        scope: SafetyControlScope,
        target: str,
    ) -> SafetyControl | None:
        if not isinstance(scope, SafetyControlScope):
            raise TypeError("scope must be a SafetyControlScope.")
        self._validate_id(target, "target")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    control_id,
                    scope,
                    target,
                    state,
                    reason,
                    activated_at,
                    activated_by_user_id,
                    incident_id,
                    resolved_at,
                    resolved_by_user_id,
                    resumed_at,
                    resumed_by_user_id
                FROM safety_controls
                WHERE scope = ?
                  AND target = ?
                  AND state = 'halted'
                LIMIT 1
                """,
                (scope.value, target),
            ).fetchone()

        return self._control_from_row(row) if row else None

    def list_active_controls(
        self,
        *,
        limit: int = 100,
    ) -> list[SafetyControl]:
        self._validate_limit(limit)

        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    control_id,
                    scope,
                    target,
                    state,
                    reason,
                    activated_at,
                    activated_by_user_id,
                    incident_id,
                    resolved_at,
                    resolved_by_user_id,
                    resumed_at,
                    resumed_by_user_id
                FROM safety_controls
                WHERE state = 'halted'
                ORDER BY activated_at DESC, control_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._control_from_row(row) for row in rows]

    def save_control(self, control: SafetyControl) -> SafetyControl:
        if not isinstance(control, SafetyControl):
            raise TypeError("control must be a SafetyControl.")

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE safety_controls
                SET
                    state = ?,
                    reason = ?,
                    resolved_at = ?,
                    resolved_by_user_id = ?,
                    resumed_at = ?,
                    resumed_by_user_id = ?
                WHERE control_id = ?
                """,
                (
                    control.state.value,
                    control.reason,
                    self._dt(control.resolved_at),
                    control.resolved_by_user_id,
                    self._dt(control.resumed_at),
                    control.resumed_by_user_id,
                    control.control_id,
                ),
            )

            if cursor.rowcount == 0:
                raise LookupError("Safety control not found.")

        return control

    @staticmethod
    def _incident_from_row(row: object) -> SafetyIncident:
        return SafetyIncident(
            incident_id=row["incident_id"],
            status=SafetyIncidentStatus(row["status"]),
            reason=row["reason"],
            created_at=datetime_from_storage(row["created_at"]),
            created_by_user_id=row["created_by_user_id"],
            resolved_at=(
                datetime_from_storage(row["resolved_at"])
                if row["resolved_at"] is not None
                else None
            ),
            resolved_by_user_id=row["resolved_by_user_id"],
            verification_notes=row["verification_notes"],
            verified_at=(
                datetime_from_storage(row["verified_at"])
                if row["verified_at"] is not None
                else None
            ),
            verified_by_user_id=row["verified_by_user_id"],
            resume_authorized_at=(
                datetime_from_storage(row["resume_authorized_at"])
                if row["resume_authorized_at"] is not None
                else None
            ),
            resume_authorized_by_user_id=row[
                "resume_authorized_by_user_id"
            ],
            closed_at=(
                datetime_from_storage(row["closed_at"])
                if row["closed_at"] is not None
                else None
            ),
            closed_by_user_id=row["closed_by_user_id"],
        )

    @staticmethod
    def _control_from_row(row: object) -> SafetyControl:
        return SafetyControl(
            control_id=row["control_id"],
            scope=SafetyControlScope(row["scope"]),
            target=row["target"],
            state=SafetyControlState(row["state"]),
            reason=row["reason"],
            activated_at=datetime_from_storage(row["activated_at"]),
            activated_by_user_id=row["activated_by_user_id"],
            incident_id=row["incident_id"],
            resolved_at=(
                datetime_from_storage(row["resolved_at"])
                if row["resolved_at"] is not None
                else None
            ),
            resolved_by_user_id=row["resolved_by_user_id"],
            resumed_at=(
                datetime_from_storage(row["resumed_at"])
                if row["resumed_at"] is not None
                else None
            ),
            resumed_by_user_id=row["resumed_by_user_id"],
        )

    @staticmethod
    def _dt(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _validate_id(value: object, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string.")
        if len(value) > 128:
            raise ValueError(
                f"{field_name} exceeds the maximum allowed length."
            )

    @classmethod
    def _validate_limit(cls, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("limit must be an integer.")
        if value < 1 or value > cls.MAX_LIST_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {cls.MAX_LIST_LIMIT}."
            )
