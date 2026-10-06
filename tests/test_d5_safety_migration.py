import sqlite3

import pytest

from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase


def _schema_version(db: SQLiteDatabase) -> int:
    with db.connection() as connection:
        row = connection.execute(
            """
            SELECT value
            FROM persistence_metadata
            WHERE key = 'schema_version'
            """
        ).fetchone()

    assert row is not None
    return int(row[0])


def _table_names(db: SQLiteDatabase) -> set[str]:
    with db.connection() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('safety_incidents', 'safety_controls')
            """
        ).fetchall()

    return {row[0] for row in rows}


def _index_names(db: SQLiteDatabase) -> set[str]:
    with db.connection() as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND name IN (
                  'idx_safety_incidents_status_time',
                  'idx_safety_incidents_creator_time',
                  'idx_safety_controls_active_target',
                  'idx_safety_controls_scope_target_state',
                  'idx_safety_controls_incident'
              )
            """
        ).fetchall()

    return {row[0] for row in rows}


def test_fresh_database_initializes_at_current_schema(tmp_path):
    db = SQLiteDatabase(tmp_path / "fresh.db")
    db.initialize()

    assert SCHEMA_VERSION == 12
    assert _schema_version(db) == SCHEMA_VERSION

    assert _table_names(db) == {
        "safety_incidents",
        "safety_controls",
    }


def test_v7_database_migrates_to_current_schema_without_losing_existing_data(tmp_path):
    db_path = tmp_path / "migration.db"

    db = SQLiteDatabase(db_path)
    db.initialize()

    with db.transaction() as connection:
        connection.execute("DROP TABLE safety_controls")
        connection.execute("DROP TABLE safety_incidents")
        connection.execute("DROP TABLE capability_confirmations")

        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '7'
            WHERE key = 'schema_version'
            """
        )

        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "business-d5-migration",
                "D5 Migration Business",
                "Founder",
                "Assistant",
                "calm",
            ),
        )

    assert _schema_version(db) == 7
    assert _table_names(db) == set()

    db.initialize()

    assert _schema_version(db) == SCHEMA_VERSION

    assert _table_names(db) == {
        "safety_incidents",
        "safety_controls",
    }

    assert _index_names(db) == {
        "idx_safety_incidents_status_time",
        "idx_safety_incidents_creator_time",
        "idx_safety_controls_active_target",
        "idx_safety_controls_scope_target_state",
        "idx_safety_controls_incident",
    }

    with db.connection() as connection:
        row = connection.execute(
            """
            SELECT name
            FROM businesses
            WHERE business_id = ?
            """,
            ("business-d5-migration",),
        ).fetchone()

    assert row is not None
    assert row[0] == "D5 Migration Business"


def test_v8_to_v9_preserves_safety_incident_and_control_data(tmp_path):
    db_path = tmp_path / "v8-to-v9.db"

    db = SQLiteDatabase(db_path)
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-d5",
                "D5 Founder",
                "founder-d5@example.test",
            ),
        )

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
                "incident-v8-preserved",
                "investigating",
                "Existing investigation",
                "2026-01-01T00:00:00+00:00",
                "founder-d5",
            ),
        )

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
                "control-v8-preserved",
                "global",
                "platform",
                "halted",
                "Existing emergency halt",
                "2026-01-01T00:01:00+00:00",
                "founder-d5",
                "incident-v8-preserved",
            ),
        )

        connection.execute("DROP TABLE capability_confirmations")

        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '8'
            WHERE key = 'schema_version'
            """
        )

    assert _schema_version(db) == 8

    db.initialize()

    assert _schema_version(db) == SCHEMA_VERSION

    with db.connection() as connection:
        incident = connection.execute(
            """
            SELECT
                incident_id,
                status,
                reason,
                created_by_user_id
            FROM safety_incidents
            WHERE incident_id = ?
            """,
            ("incident-v8-preserved",),
        ).fetchone()

        control = connection.execute(
            """
            SELECT
                control_id,
                scope,
                target,
                state,
                incident_id
            FROM safety_controls
            WHERE control_id = ?
            """,
            ("control-v8-preserved",),
        ).fetchone()

    assert incident is not None
    assert tuple(incident) == (
        "incident-v8-preserved",
        "investigating",
        "Existing investigation",
        "founder-d5",
    )

    assert control is not None
    assert tuple(control) == (
        "control-v8-preserved",
        "global",
        "platform",
        "halted",
        "incident-v8-preserved",
    )


def test_safety_incident_constraints_match_recovery_lifecycle(tmp_path):
    db = SQLiteDatabase(tmp_path / "constraints.db")
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-d5",
                "D5 Founder",
                "founder-d5@example.test",
            ),
        )

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
                "incident-investigating",
                "investigating",
                "Investigation in progress",
                "2026-01-01T00:00:00+00:00",
                "founder-d5",
            ),
        )

        connection.execute(
            """
            INSERT INTO safety_incidents(
                incident_id,
                status,
                reason,
                created_at,
                created_by_user_id,
                resolved_at,
                resolved_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "incident-resolved",
                "resolved",
                "Root cause fixed",
                "2026-01-01T00:00:00+00:00",
                "founder-d5",
                "2026-01-01T01:00:00+00:00",
                "founder-d5",
            ),
        )

        connection.execute(
            """
            INSERT INTO safety_incidents(
                incident_id,
                status,
                reason,
                created_at,
                created_by_user_id,
                resolved_at,
                resolved_by_user_id,
                verification_notes,
                verified_at,
                verified_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "incident-verified",
                "verified",
                "Fix verified",
                "2026-01-01T00:00:00+00:00",
                "founder-d5",
                "2026-01-01T01:00:00+00:00",
                "founder-d5",
                "Regression passed",
                "2026-01-01T02:00:00+00:00",
                "founder-d5",
            ),
        )



def test_invalid_closed_incident_is_rejected(tmp_path):
    db = SQLiteDatabase(tmp_path / "invalid-closed.db")
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-d5",
                "D5 Founder",
                "founder-d5@example.test",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
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
                    "incident-invalid-closed",
                    "closed",
                    "Invalid lifecycle state",
                    "2026-01-01T00:00:00+00:00",
                    "founder-d5",
                ),
            )


def test_halted_control_target_is_unique(tmp_path):
    db = SQLiteDatabase(tmp_path / "control-uniqueness.db")
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-d5",
                "D5 Founder",
                "founder-controls@example.test",
            ),
        )

        connection.execute(
            """
            INSERT INTO safety_controls(
                control_id,
                scope,
                target,
                state,
                reason,
                activated_at,
                activated_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "control-1",
                "global",
                "platform",
                "halted",
                "incident response",
                "2026-01-01T00:00:00+00:00",
                "founder-d5",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO safety_controls(
                    control_id,
                    scope,
                    target,
                    state,
                    reason,
                    activated_at,
                    activated_by_user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "control-2",
                    "global",
                    "platform",
                    "halted",
                    "duplicate halt",
                    "2026-01-01T00:01:00+00:00",
                    "founder-d5",
                ),
            )


def test_current_safety_tables_are_reused_on_restart(tmp_path):
    db = SQLiteDatabase(tmp_path / "restart.db")
    db.initialize()

    reopened = SQLiteDatabase(tmp_path / "restart.db")
    reopened.initialize()

    assert _schema_version(reopened) == SCHEMA_VERSION

    assert _table_names(reopened) == {
        "safety_incidents",
        "safety_controls",
    }
