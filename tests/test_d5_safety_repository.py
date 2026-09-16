from datetime import datetime, timezone

import pytest

from app.persistence.database import SQLiteDatabase
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import (
    SafetyControl,
    SafetyControlScope,
    SafetyControlState,
    SafetyIncident,
    SafetyIncidentStatus,
)


def _db(tmp_path) -> SQLiteDatabase:
    db = SQLiteDatabase(tmp_path / "safety.db")
    db.initialize()
    return db


def _founder(db: SQLiteDatabase, user_id: str = "founder-d5") -> None:
    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (user_id, "D5 Founder", f"{user_id}@example.test"),
        )


def _incident(
    user_id: str = "founder-d5",
    incident_id: str = "incident-1",
) -> SafetyIncident:
    return SafetyIncident(
        incident_id=incident_id,
        status=SafetyIncidentStatus.OPEN,
        reason="Emergency safety investigation",
        created_at=datetime.now(timezone.utc),
        created_by_user_id=user_id,
    )


def _halted_control(
    incident_id: str = "incident-1",
    control_id: str = "control-1",
) -> SafetyControl:
    return SafetyControl(
        control_id=control_id,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        state=SafetyControlState.HALTED,
        reason="Emergency platform halt",
        activated_at=datetime.now(timezone.utc),
        activated_by_user_id="founder-d5",
        incident_id=incident_id,
    )


def test_incident_round_trip(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    incident = _incident()

    repository.create_incident(incident)

    loaded = repository.get_incident(incident.incident_id)

    assert loaded == incident


def test_halted_control_round_trip(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())

    control = _halted_control()
    repository.create_control(control)

    loaded = repository.get_control(control.control_id)

    assert loaded == control


def test_active_halt_is_discoverable_by_scope_and_target(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())
    repository.create_control(_halted_control())

    loaded = repository.get_active_control(
        SafetyControlScope.GLOBAL,
        "platform",
    )

    assert loaded is not None
    assert loaded.control_id == "control-1"
    assert loaded.state is SafetyControlState.HALTED


def test_resuming_control_requires_resolution_and_resume_evidence(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())
    repository.create_control(_halted_control())

    with pytest.raises(ValueError):
        repository.save_control(
            SafetyControl(
                control_id="control-1",
                scope=SafetyControlScope.GLOBAL,
                target="platform",
                state=SafetyControlState.ACTIVE,
                reason="Resumed without evidence",
                activated_at=datetime.now(timezone.utc),
                activated_by_user_id="founder-d5",
                incident_id="incident-1",
            )
        )


def test_database_restart_preserves_halt(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())
    repository.create_control(_halted_control())

    reopened = SQLiteDatabase(tmp_path / "safety.db")
    reopened.initialize()

    loaded = SQLiteSafetyRepository(reopened).get_active_control(
        SafetyControlScope.GLOBAL,
        "platform",
    )

    assert loaded is not None
    assert loaded.state is SafetyControlState.HALTED


def test_cross_scope_lookup_does_not_return_unrelated_halt(tmp_path):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())
    repository.create_control(_halted_control())

    assert (
        repository.get_active_control(
            SafetyControlScope.BUSINESS,
            "another-business",
        )
        is None
    )


def test_duplicate_halted_control_for_same_scope_and_target_is_rejected(
    tmp_path,
):
    db = _db(tmp_path)
    _founder(db)

    repository = SQLiteSafetyRepository(db)
    repository.create_incident(_incident())
    repository.create_control(_halted_control())

    duplicate = SafetyControl(
        control_id="control-2",
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        state=SafetyControlState.HALTED,
        reason="Second emergency halt",
        activated_at=datetime.now(timezone.utc),
        activated_by_user_id="founder-d5",
        incident_id="incident-1",
    )

    with pytest.raises(Exception):
        repository.create_control(duplicate)
