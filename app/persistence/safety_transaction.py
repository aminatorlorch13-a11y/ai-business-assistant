from __future__ import annotations

import json
import sqlite3

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import datetime_to_storage
from app.platform.events import PlatformEvent
from app.safety.models import SafetyControl, SafetyIncident


class SQLiteSafetyTransaction:
    """
    Atomic persistence boundary for safety mutations and their evidence.

    A single SQLite transaction owns all safety state changes and audit-event
    writes performed through this object. Callers must explicitly commit or
    rollback.
    """

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")

        self._database = database
        self._connection_context = database.connection()
        self._connection = self._connection_context.__enter__()
        self._completed = False

        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except Exception:
            self._connection_context.__exit__(*__import__("sys").exc_info())
            self._connection = None
            self._completed = True
            raise

    def _ensure_open(self) -> sqlite3.Connection:
        if self._completed or self._connection is None:
            raise RuntimeError("Transaction is already completed.")
        return self._connection

    def create_incident(self, incident: SafetyIncident) -> SafetyIncident:
        connection = self._ensure_open()

        if not isinstance(incident, SafetyIncident):
            raise TypeError("incident must be a SafetyIncident.")

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
                datetime_to_storage(incident.created_at),
                incident.created_by_user_id,
            ),
        )

        return incident

    def create_control(self, control: SafetyControl) -> SafetyControl:
        connection = self._ensure_open()

        if not isinstance(control, SafetyControl):
            raise TypeError("control must be a SafetyControl.")

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
                datetime_to_storage(control.activated_at),
                control.activated_by_user_id,
                control.incident_id,
            ),
        )

        return control

    def save_incident(self, incident: SafetyIncident) -> SafetyIncident:
        connection = self._ensure_open()

        if not isinstance(incident, SafetyIncident):
            raise TypeError("incident must be a SafetyIncident.")

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

    def save_control(self, control: SafetyControl) -> SafetyControl:
        connection = self._ensure_open()

        if not isinstance(control, SafetyControl):
            raise TypeError("control must be a SafetyControl.")

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

    def append_event(self, event: PlatformEvent) -> PlatformEvent:
        connection = self._ensure_open()

        if not isinstance(event, PlatformEvent):
            raise TypeError("event must be a PlatformEvent.")

        metadata_json = json.dumps(
            event.metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        if event.business_id is not None:
            row = connection.execute(
                """
                SELECT 1
                FROM businesses
                WHERE business_id = ?
                """,
                (event.business_id,),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "business_id does not reference an existing business."
                )

        if event.user_id is not None:
            row = connection.execute(
                """
                SELECT 1
                FROM users
                WHERE user_id = ?
                """,
                (event.user_id,),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "user_id does not reference an existing user."
                )

        try:
            connection.execute(
                """
                INSERT INTO platform_events(
                    event_id,
                    occurred_at,
                    event_type,
                    business_id,
                    user_id,
                    channel,
                    actor_type,
                    action,
                    outcome,
                    correlation_id,
                    metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.storage_occurred_at(),
                    event.event_type,
                    event.business_id,
                    event.user_id,
                    event.channel.value,
                    event.actor_type.value,
                    event.action,
                    event.outcome.value,
                    event.correlation_id,
                    metadata_json,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError(
                    "A platform event with this event_id already exists."
                ) from exc
            raise

        return event

    def commit(self) -> None:
        connection = self._ensure_open()

        try:
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            finally:
                self._close()
            raise
        else:
            self._close()

    def rollback(self) -> None:
        connection = self._ensure_open()

        try:
            connection.rollback()
        finally:
            self._close()

    def _close(self) -> None:
        if self._completed:
            return

        self._completed = True
        self._connection = None
        self._connection_context.__exit__(None, None, None)

    @staticmethod
    def _dt(value):
        return datetime_to_storage(value) if value is not None else None
