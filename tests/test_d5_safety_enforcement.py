from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.persistence.database import SQLiteDatabase
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.enforcement import SafetyEnforcement
from app.safety.models import (
    SafetyControl,
    SafetyControlScope,
    SafetyControlState,
    SafetyIncident,
    SafetyIncidentStatus,
)
from app.services.business_operation import BusinessOperation
from app.trust.action_policy import ActionPolicy


class RecordingOperation(BusinessOperation):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, action, tenant=None) -> str:
        self.calls.append(action.action_type)
        return "operation executed"


def make_database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "safety-enforcement.db")
    database.initialize()
    return database


def create_founder_user(
    database: SQLiteDatabase,
    user_id: str = "founder-d5",
) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (user_id, "D5 Founder", f"{user_id}@example.test"),
        )


def create_incident(
    repository: SQLiteSafetyRepository,
    *,
    incident_id: str,
    user_id: str = "founder-d5",
) -> None:
    incident = SafetyIncident(
        incident_id=incident_id,
        status=SafetyIncidentStatus.OPEN,
        reason="Emergency safety enforcement test",
        created_at=datetime.now(timezone.utc),
        created_by_user_id=user_id,
    )
    repository.create_incident(incident)


def create_halted_control(
    repository: SQLiteSafetyRepository,
    *,
    scope: SafetyControlScope,
    target: str,
    incident_id: str,
    user_id: str = "founder-d5",
) -> None:
    control = SafetyControl(
        control_id=f"control-{scope.value}-{target}",
        scope=scope,
        target=target,
        state=SafetyControlState.HALTED,
        reason="Emergency safety test",
        activated_at=datetime.now(timezone.utc),
        activated_by_user_id=user_id,
        incident_id=incident_id,
    )
    repository.create_control(control)


def make_action(
    *,
    business_id: str = "business-1",
    action_type: str = "create",
) -> AssistantAction:
    return AssistantAction(
        business_id=business_id,
        action_type=action_type,
        target="assistant",
        instruction="Perform the requested operation.",
    )


def build_executor(
    operation: RecordingOperation,
    database: SQLiteDatabase,
) -> ActionExecutor:
    repository = SQLiteSafetyRepository(database)
    safety_enforcement = SafetyEnforcement(repository)

    return ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=safety_enforcement,
    )


def test_business_halt_must_block_action_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-business",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        incident_id="incident-business",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)

    action = make_action(business_id="business-1")

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []


def test_other_business_is_not_blocked_by_business_halt(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-business",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        incident_id="incident-business",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)

    action = make_action(business_id="business-2")

    assert executor.execute(action, confirmed=True) == "operation executed"
    assert operation.calls == ["create"]


def test_global_halt_must_block_any_business(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-global",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        incident_id="incident-global",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)

    action = make_action(business_id="business-1")

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []


def test_safety_state_failure_must_fail_closed(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    create_founder_user(database)

    def fail_to_read_safety_state(self, scope, target):
        raise RuntimeError("simulated safety-state database failure")

    monkeypatch.setattr(
        SQLiteSafetyRepository,
        "get_active_control",
        fail_to_read_safety_state,
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)
    action = make_action()

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []

def test_business_halt_survives_database_restart(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)

    create_incident(
        repository,
        incident_id="incident-restart",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        incident_id="incident-restart",
    )

    # Simulate a fresh process using the same persistent database.
    restarted_database = SQLiteDatabase(
        tmp_path / "safety-enforcement.db"
    )
    restarted_database.initialize()

    operation = RecordingOperation()
    executor = build_executor(
        operation,
        restarted_database,
    )
    action = make_action(business_id="business-1")

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []




def test_capability_halt_must_block_matching_action_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-capability",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.CAPABILITY,
        target="create",
        incident_id="incident-capability",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)
    action = make_action(action_type="create")

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []


def test_capability_halt_does_not_block_different_capability(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-capability",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.CAPABILITY,
        target="create",
        incident_id="incident-capability",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)
    action = make_action(action_type="update")

    assert executor.execute(action, confirmed=True) == "operation executed"
    assert operation.calls == ["update"]


def test_channel_halt_must_block_matching_channel_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-channel",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.CHANNEL,
        target="web",
        incident_id="incident-channel",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)
    action = make_action()

    with pytest.raises(PermissionError):
        executor.execute(
            action,
            confirmed=True,
            channel="web",
        )

    assert operation.calls == []


def test_integration_halt_must_block_matching_integration_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-integration",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.INTEGRATION,
        target="business_operation",
        incident_id="incident-integration",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)
    action = make_action()

    with pytest.raises(PermissionError):
        executor.execute(
            action,
            confirmed=True,
            integration="business_operation",
        )

    assert operation.calls == []


def test_safety_control_scope_isolation_does_not_cross_block_unrelated_scope(
    tmp_path,
):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)
    create_incident(
        repository,
        incident_id="incident-scope-isolation",
    )
    create_halted_control(
        repository,
        scope=SafetyControlScope.CAPABILITY,
        target="create",
        incident_id="incident-scope-isolation",
    )

    operation = RecordingOperation()
    executor = build_executor(operation, database)

    unrelated_action = make_action(action_type="update")

    assert executor.execute(
        unrelated_action,
        confirmed=True,
    ) == "operation executed"

    assert operation.calls == ["update"]

def test_no_halt_allows_execution(tmp_path):
    database = make_database(tmp_path)
    create_founder_user(database)

    repository = SQLiteSafetyRepository(database)

    operation = RecordingOperation()
    executor = build_executor(operation, database)

    action = make_action()

    assert executor.execute(action, confirmed=True) == "operation executed"
    assert operation.calls == ["create"]
