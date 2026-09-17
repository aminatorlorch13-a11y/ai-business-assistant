from unittest.mock import Mock

import pytest

from app.assistant.action import AssistantAction
from app.assistant.action_executor import (
    ActionExecutor,
    ActionOperationError,
    ActionPolicyDeniedError,
)
from app.assistant.execution_errors import ActionConfirmationRequiredError
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.platform_event_repository import (
    SQLitePlatformEventRepository,
)
from app.platform.events import PlatformEventOutcome
from app.services.business_operation import BusinessOperation
from app.telemetry.platform_events import PlatformEventExecutionTelemetry
from app.trust.action_policy import ActionPolicy
from app.trust.action_safety import ActionSafetyPolicy
from tests.test_safety_helpers import AllowAllTestSafetyEnforcement


def make_action(action_type: str = "create") -> AssistantAction:
    return AssistantAction(
        business_id="business-001",
        action_type=action_type,
        target="appointment",
        instruction="Perform the requested operation.",
    )


def make_executor(
    operation,
    telemetry=None,
    policy=None,
    safety_policy=None,
):
    if policy is None:
        policy = ActionPolicy()

    if safety_policy is None:
        safety_policy = ActionSafetyPolicy(
            require_confirmation_for_create=False,
            require_confirmation_for_update=False,
            require_confirmation_for_delete=False,
        )

    return ActionExecutor(
        policy=policy,
        operation=operation,
        safety_enforcement=AllowAllTestSafetyEnforcement(),
        safety_policy=safety_policy,
        telemetry=telemetry,
    )


def make_database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()

    business = Business(
        business_id="business-001",
        name="Test Business",
        owner_name="Test Owner",
        assistant_name="Test Assistant",
        assistant_voice="male",
    )
    SQLiteBusinessRepository(database).save(business)

    return database


def test_successful_execution_is_persisted(tmp_path):
    database = make_database(tmp_path)
    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Operation completed."

    executor = make_executor(operation, telemetry=telemetry)

    result = executor.execute(
        make_action(),
        confirmed=True,
        channel="web",
        integration="calendar",
    )

    assert result == "Operation completed."

    events = repository.list_recent(limit=10)
    assert len(events) == 1

    event = events[0]
    assert event.event_type == "assistant.execution"
    assert event.business_id == "business-001"
    assert event.channel.value == "web"
    assert event.action == "create"
    assert event.outcome is PlatformEventOutcome.SUCCESS
    assert event.metadata == {
        "action_type": "create",
        "integration": "calendar",
    }


def test_operation_failure_is_persisted_and_original_error_semantics_remain(
    tmp_path,
):
    database = make_database(tmp_path)
    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    operation.execute.side_effect = RuntimeError("provider failed")

    executor = make_executor(operation, telemetry=telemetry)

    with pytest.raises(
        ActionOperationError,
        match="The business operation failed.",
    ):
        executor.execute(
            make_action(),
            channel="web",
            integration="calendar",
        )

    events = repository.list_recent(limit=10)
    assert len(events) == 1
    assert events[0].outcome is PlatformEventOutcome.FAILURE
    assert events[0].metadata["reason"] == "operation_failed"


def test_policy_denial_is_persisted_without_executing_operation(tmp_path):
    database = make_database(tmp_path)
    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    policy = ActionPolicy(allow_create=False)

    executor = make_executor(
        operation,
        telemetry=telemetry,
        policy=policy,
    )

    with pytest.raises(ActionPolicyDeniedError):
        executor.execute(
            make_action(),
            confirmed=True,
            channel="web",
        )

    operation.execute.assert_not_called()

    events = repository.list_recent(limit=10)
    assert len(events) == 1
    assert events[0].outcome is PlatformEventOutcome.DENIED
    assert events[0].metadata["reason"] == "action_policy_denied"


def test_confirmation_denial_is_persisted_without_executing_operation(tmp_path):
    database = make_database(tmp_path)
    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    safety_policy = ActionSafetyPolicy(
        require_confirmation_for_create=True,
        require_confirmation_for_update=False,
        require_confirmation_for_delete=False,
    )

    executor = make_executor(
        operation,
        telemetry=telemetry,
        safety_policy=safety_policy,
    )

    with pytest.raises(ActionConfirmationRequiredError):
        executor.execute(
            make_action(),
            confirmed=False,
            channel="web",
        )

    operation.execute.assert_not_called()

    events = repository.list_recent(limit=10)
    assert len(events) == 1
    assert events[0].outcome is PlatformEventOutcome.DENIED
    assert events[0].metadata["reason"] == "confirmation_required"


def test_telemetry_failure_does_not_break_successful_execution():
    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Operation completed."

    telemetry = Mock()
    telemetry.record.side_effect = RuntimeError("telemetry unavailable")

    executor = make_executor(operation, telemetry=telemetry)

    result = executor.execute(
        make_action(),
        confirmed=True,
        channel="web",
    )

    assert result == "Operation completed."


def test_telemetry_failure_does_not_mask_operation_failure():
    operation = Mock(spec=BusinessOperation)
    operation.execute.side_effect = RuntimeError("provider failed")

    telemetry = Mock()
    telemetry.record.side_effect = RuntimeError("telemetry unavailable")

    executor = make_executor(operation, telemetry=telemetry)

    with pytest.raises(
        ActionOperationError,
        match="The business operation failed.",
    ):
        executor.execute(
            make_action(),
            channel="web",
        )


def test_tenant_user_identity_is_recorded_from_authenticated_context(tmp_path):
    database = make_database(tmp_path)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "user-001",
                "Test User",
                "user-001@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO business_memberships(user_id, business_id, role)
            VALUES (?, ?, ?)
            """,
            (
                "user-001",
                "business-001",
                UserRole.OWNER.value,
            ),
        )

    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = "Operation completed."

    principal = AuthenticatedPrincipal(
        user_id="user-001",
        business_id="business-001",
        role=UserRole.OWNER,
        session_id="session-001",
    )
    tenant = TenantContext(
        business_id="business-001",
        principal=principal,
    )

    executor = make_executor(operation, telemetry=telemetry)

    executor.execute(
        make_action(),
        confirmed=True,
        tenant=tenant,
        channel="web",
    )

    events = repository.list_recent(limit=10)
    assert len(events) == 1
    assert events[0].user_id == "user-001"


def test_execution_telemetry_does_not_record_action_instruction_or_result(
    tmp_path,
):
    database = make_database(tmp_path)
    repository = SQLitePlatformEventRepository(database)
    telemetry = PlatformEventExecutionTelemetry(repository)

    operation = Mock(spec=BusinessOperation)
    operation.execute.return_value = (
        "PRIVATE CUSTOMER RESULT THAT MUST NOT ENTER TELEMETRY"
    )

    action = AssistantAction(
        business_id="business-001",
        action_type="create",
        target="appointment",
        instruction="PRIVATE CUSTOMER INSTRUCTION",
    )

    executor = make_executor(operation, telemetry=telemetry)

    executor.execute(
        action,
        confirmed=True,
        channel="web",
        integration="calendar",
    )

    events = repository.list_recent(limit=10)
    assert len(events) == 1

    event = events[0]
    assert "PRIVATE CUSTOMER INSTRUCTION" not in str(event.metadata)
    assert "PRIVATE CUSTOMER RESULT" not in str(event.metadata)
    assert "instruction" not in event.metadata
    assert "result" not in event.metadata
