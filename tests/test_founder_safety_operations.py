from __future__ import annotations

from pathlib import Path

import pytest

from app.founder.authorization import FounderAuthorizationService
from app.founder.safety_operations import FounderSafetyOperationsService
from app.identity.models import AuthenticatedPrincipal, SessionScope, UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import (
    SafetyControlScope,
    SafetyControlState,
    SafetyIncidentStatus,
)
from app.safety.service import SafetyControlError, SafetyControlService


def _setup(tmp_path: Path):
    db = SQLiteDatabase(tmp_path / "d6_2.db")
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO businesses(business_id,name,owner_name,assistant_name,assistant_voice) VALUES (?,?,?,?,?)",
            ("business-1","Test Business","Founder One","Assistant","male"),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-1",
                "Founder One",
                "founder1@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "user-1",
                "Normal User",
                "user1@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_founders(user_id, active)
            VALUES (?, 1)
            """,
            ("founder-1",),
        )

    founders = SQLiteFounderRepository(db)
    safety_repository = SQLiteSafetyRepository(db)
    events = SQLitePlatformEventRepository(db)
    founder_authorization = FounderAuthorizationService(founders)
    safety_service = SafetyControlService(
        safety_repository,
        founder_authorization,
        events,
    )
    operations = FounderSafetyOperationsService(
        safety_repository=safety_repository,
        safety_service=safety_service,
        founder_authorization=founder_authorization,
    )

    founder = AuthenticatedPrincipal(
        user_id="founder-1",
        business_id=None,
        role=None,
        session_id="founder-session",
        scope=SessionScope.PLATFORM,
    )

    normal_user = AuthenticatedPrincipal(
        user_id="user-1",
        business_id="business-1",
        role=UserRole.OWNER,
        session_id="user-session",
    )

    return (
        db,
        safety_repository,
        events,
        safety_service,
        operations,
        founder,
        normal_user,
    )


def test_non_founder_cannot_read_controls(tmp_path):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        _founder,
        normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(PermissionError):
        operations.list_active_controls(normal_user)


def test_non_founder_cannot_read_control(tmp_path):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        _founder,
        normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(PermissionError):
        operations.get_control(normal_user, "missing-control")


def test_non_founder_cannot_read_incident(tmp_path):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        _founder,
        normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(PermissionError):
        operations.get_incident(normal_user, "missing-incident")


def test_non_founder_cannot_halt(tmp_path):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        _founder,
        normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(PermissionError):
        operations.halt(
            normal_user,
            scope=SafetyControlScope.BUSINESS,
            target="business-1",
            reason="Unauthorized attempt",
        )


def test_founder_can_read_and_mutate_through_facade(tmp_path):
    (
        _db,
        repository,
        events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    control = operations.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Operational emergency",
    )

    assert control.state is SafetyControlState.HALTED
    assert control.incident_id

    active = operations.list_active_controls(founder)

    assert len(active) == 1
    assert active[0].control_id == control.control_id

    stored_control = operations.get_control(
        founder,
        control.control_id,
    )

    assert stored_control is not None
    assert stored_control.state is SafetyControlState.HALTED

    incident = operations.get_incident(
        founder,
        control.incident_id,
    )

    assert incident is not None
    assert incident.status is SafetyIncidentStatus.OPEN

    recent_events = events.list_recent(limit=20)

    assert any(
        event.action == "safety.halt"
        and event.user_id == "founder-1"
        for event in recent_events
    )

    # Confirm the facade did not merely return an in-memory object.
    assert repository.get_control(control.control_id) is not None


def test_founder_facade_routes_full_recovery_lifecycle(tmp_path):
    (
        _db,
        repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    control = operations.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        reason="Business emergency",
    )

    incident = operations.begin_investigation(
        founder,
        control.incident_id,
    )
    assert incident.status is SafetyIncidentStatus.INVESTIGATING

    incident = operations.resolve_incident(
        founder,
        control.incident_id,
        notes="Root cause fixed.",
    )
    assert incident.status is SafetyIncidentStatus.RESOLVED

    incident = operations.verify_fix(
        founder,
        control.incident_id,
        notes="Regression checks passed.",
    )
    assert incident.status is SafetyIncidentStatus.VERIFIED

    incident = operations.authorize_resume(
        founder,
        control.incident_id,
    )
    assert incident.status is SafetyIncidentStatus.RESUME_AUTHORIZED

    resumed = operations.resume_control(
        founder,
        control.control_id,
    )
    assert resumed.state is SafetyControlState.ACTIVE

    closed = operations.close_incident(
        founder,
        control.incident_id,
    )
    assert closed.status is SafetyIncidentStatus.CLOSED

    assert repository.get_control(control.control_id).state is SafetyControlState.ACTIVE


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("get_control", ("",)),
        ("get_incident", ("",)),
    ],
)
def test_invalid_identifiers_are_rejected(
    tmp_path,
    method_name,
    args,
):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    method = getattr(operations, method_name)

    with pytest.raises(ValueError):
        method(founder, *args)


@pytest.mark.parametrize(
    "limit",
    [0, -1, 101, True, False, "10"],
)
def test_invalid_limits_are_rejected(tmp_path, limit):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        operations.list_active_controls(
            founder,
            limit=limit,
        )


@pytest.mark.parametrize(
    "reason",
    ["", "   "],
)
def test_invalid_halt_reason_is_rejected(tmp_path, reason):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(ValueError):
        operations.halt(
            founder,
            scope=SafetyControlScope.GLOBAL,
            target="platform",
            reason=reason,
        )


@pytest.mark.parametrize(
    "notes",
    ["", "   "],
)
def test_invalid_recovery_notes_are_rejected(tmp_path, notes):
    (
        _db,
        _repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    control = operations.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency",
    )

    operations.begin_investigation(
        founder,
        control.incident_id,
    )

    with pytest.raises(ValueError):
        operations.resolve_incident(
            founder,
            control.incident_id,
            notes=notes,
        )


def test_invalid_scope_is_rejected_before_mutation(tmp_path):
    (
        _db,
        repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    with pytest.raises(TypeError):
        operations.halt(
            founder,
            scope="global",
            target="platform",
            reason="Invalid scope",
        )

    assert repository.list_active_controls(limit=100) == []


def test_read_repository_and_service_must_share_database(tmp_path):
    db_one = SQLiteDatabase(tmp_path / "one.db")
    db_two = SQLiteDatabase(tmp_path / "two.db")

    db_one.initialize()
    db_two.initialize()

    with db_one.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-1",
                "Founder One",
                "founder1@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_founders(user_id, active)
            VALUES (?, 1)
            """,
            ("founder-1",),
        )

    founders = SQLiteFounderRepository(db_one)
    founder_authorization = FounderAuthorizationService(founders)

    repository_one = SQLiteSafetyRepository(db_one)
    repository_two = SQLiteSafetyRepository(db_two)
    events = SQLitePlatformEventRepository(db_one)

    safety_service = SafetyControlService(
        repository_one,
        founder_authorization,
        events,
    )

    with pytest.raises(ValueError):
        FounderSafetyOperationsService(
            safety_repository=repository_two,
            safety_service=safety_service,
            founder_authorization=founder_authorization,
        )


def test_facade_does_not_bypass_safety_lifecycle(tmp_path):
    (
        _db,
        repository,
        _events,
        _service,
        operations,
        founder,
        _normal_user,
    ) = _setup(tmp_path)

    control = operations.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency",
    )

    # Direct persistence manipulation is intentionally outside the facade.
    # The facade itself must require the proper lifecycle.
    with pytest.raises(SafetyControlError):
        operations.resume_control(
            founder,
            control.control_id,
        )

    stored = repository.get_control(control.control_id)

    assert stored is not None
    assert stored.state is SafetyControlState.HALTED
