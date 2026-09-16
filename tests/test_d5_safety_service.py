from app.founder.authorization import FounderAuthorizationService
from app.assistant.action import AssistantAction
from app.assistant.action_executor import ActionExecutor
from app.safety.enforcement import SafetyEnforcement
from app.trust.action_policy import ActionPolicy
from app.services.business_operation import BusinessOperation
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.persistence.database import SQLiteDatabase
from app.persistence.founder_repository import SQLiteFounderRepository
from app.persistence.platform_event_repository import SQLitePlatformEventRepository
from app.persistence.safety_repository import SQLiteSafetyRepository
from app.safety.models import SafetyControlScope, SafetyControlState, SafetyIncidentStatus
from app.safety.service import SafetyControlError, SafetyControlService
import pytest


def _setup(tmp_path):
    db = SQLiteDatabase(tmp_path / "service.db")
    db.initialize()

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-1",
                "Founder",
                "founder@example.test",
            ),
        )

        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "user-2",
                "User",
                "user@example.test",
            ),
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
                "business-1",
                "Test Business",
                "Founder",
                "Test Assistant",
                "male",
            ),
        )

        connection.execute(
            """
            INSERT INTO platform_founders(user_id, active)
            VALUES (?, 1)
            """,
            ("founder-1",),
        )

    founder_repo = SQLiteFounderRepository(db)
    events = SQLitePlatformEventRepository(db)
    safety = SQLiteSafetyRepository(db)

    service = SafetyControlService(
        safety,
        FounderAuthorizationService(founder_repo),
        events,
    )

    founder = AuthenticatedPrincipal(
        user_id="founder-1",
        business_id="platform",
        role=UserRole.OWNER,
        session_id="founder-session",
    )

    user = AuthenticatedPrincipal(
        user_id="user-2",
        business_id="platform",
        role=UserRole.OWNER,
        session_id="user-session",
    )

    return db, service, events, safety, founder, user


def test_founder_can_halt_and_complete_full_recovery_lifecycle(tmp_path):
    (
        db,
        service,
        events,
        safety,
        founder,
        _,
    ) = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency test halt",
    )

    assert control.state.value == "halted"

    incident = safety.get_incident(control.incident_id)

    assert incident is not None
    assert incident.status is SafetyIncidentStatus.OPEN

    incident = service.begin_investigation(
        founder,
        control.incident_id,
    )

    assert incident.status is SafetyIncidentStatus.INVESTIGATING

    incident = service.resolve_incident(
        founder,
        control.incident_id,
        notes="Root cause isolated and corrected.",
    )

    assert incident.status is SafetyIncidentStatus.RESOLVED

    incident = service.verify_fix(
        founder,
        control.incident_id,
        notes="Regression and attack tests passed.",
    )

    assert incident.status is SafetyIncidentStatus.VERIFIED

    incident = service.authorize_resume(
        founder,
        control.incident_id,
    )

    assert incident.status is SafetyIncidentStatus.RESUME_AUTHORIZED

    resumed = service.resume_control(
        founder,
        control.control_id,
    )

    assert resumed.state.value == "active"

    closed = service.close_incident(
        founder,
        control.incident_id,
    )

    assert closed.status is SafetyIncidentStatus.CLOSED

    recent_events = events.list_recent(limit=50)

    assert any(
        event.action == "safety.halt"
        and event.user_id == "founder-1"
        and event.actor_type.value == "founder"
        for event in recent_events
    )

    assert db.path.exists()


class RecordingOperation(BusinessOperation):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, action, tenant=None) -> str:
        self.calls.append(action.action_type)
        return "operation executed"


def test_execution_resumes_only_after_full_safety_recovery(tmp_path):
    (
        _,
        service,
        _,
        safety,
        founder,
        _,
    ) = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    operation = RecordingOperation()
    enforcement = SafetyEnforcement(safety)
    executor = ActionExecutor(
        policy=ActionPolicy(),
        operation=operation,
        safety_enforcement=enforcement,
    )

    action = AssistantAction(
        business_id="business-1",
        action_type="create",
        target="assistant",
        instruction="Perform the requested operation.",
    )

    with pytest.raises(PermissionError):
        executor.execute(action, confirmed=True)

    assert operation.calls == []

    service.begin_investigation(
        founder,
        control.incident_id,
    )
    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Root cause isolated and corrected.",
    )
    service.verify_fix(
        founder,
        control.incident_id,
        notes="Regression and attack tests passed.",
    )
    service.authorize_resume(
        founder,
        control.incident_id,
    )

    resumed = service.resume_control(
        founder,
        control.control_id,
    )

    assert resumed.state.value == "active"

    assert executor.execute(
        action,
        confirmed=True,
    ) == "operation executed"

    assert operation.calls == ["create"]


def test_halt_rolls_back_when_audit_write_fails(tmp_path, monkeypatch):
    (
        database,
        service,
        _,
        safety,
        founder,
        _,
    ) = _setup(tmp_path)

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.halt(
            founder,
            scope=SafetyControlScope.GLOBAL,
            target="platform",
            reason="Emergency execution halt",
        )

    assert safety.get_active_control(
        SafetyControlScope.GLOBAL,
        "platform",
    ) is None

    with database.connection() as incidents:
        row = incidents.execute(
            "SELECT COUNT(*) AS count FROM safety_incidents"
        ).fetchone()

    assert row["count"] == 0




def test_begin_investigation_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.begin_investigation(
            founder,
            control.incident_id,
        )

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "open"


def test_resolve_incident_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.resolve_incident(
            founder,
            control.incident_id,
            notes="Issue fixed",
        )

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "investigating"


def test_verify_fix_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )
    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Issue fixed",
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.verify_fix(
            founder,
            control.incident_id,
            notes="Fix independently verified",
        )

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "resolved"


def test_authorize_resume_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )
    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Issue fixed",
    )
    service.verify_fix(
        founder,
        control.incident_id,
        notes="Fix independently verified",
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.authorize_resume(
            founder,
            control.incident_id,
        )

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "verified"


def test_resume_control_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )
    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Issue fixed",
    )
    service.verify_fix(
        founder,
        control.incident_id,
        notes="Fix independently verified",
    )
    service.authorize_resume(
        founder,
        control.incident_id,
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.resume_control(
            founder,
            control.control_id,
        )

    current_control = safety.get_control(control.control_id)
    assert current_control.state.value == "halted"

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "resume_authorized"


def test_close_incident_rolls_back_when_audit_write_fails(
    tmp_path, monkeypatch
):
    _, service, _, safety, founder, _ = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency execution halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )
    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Issue fixed",
    )
    service.verify_fix(
        founder,
        control.incident_id,
        notes="Fix independently verified",
    )
    service.authorize_resume(
        founder,
        control.incident_id,
    )
    service.resume_control(
        founder,
        control.control_id,
    )

    def fail_append(self, event):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(
        "app.persistence.safety_transaction.SQLiteSafetyTransaction.append_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        service.close_incident(
            founder,
            control.incident_id,
        )

    incident = safety.get_incident(control.incident_id)
    assert incident.status.value == "resume_authorized"

def test_safety_recovery_cannot_restore_expired_commercial_access(tmp_path):
    """Releasing an emergency halt must never restore expired access."""
    from app.commercial.state import CommercialStatus, BusinessCommercialState
    from app.persistence.commercial_state_repository import (
        SQLiteCommercialStateRepository,
    )
    from app.web.access import BusinessAccessDenied, BusinessAccessService

    db, service, _, safety, founder, _ = _setup(tmp_path)

    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            "business-1",
            CommercialStatus.EXPIRED,
        )
    )

    control = service.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        reason="D5 commercial-boundary attack test.",
    )

    incident_id = control.incident_id
    assert incident_id is not None

    from app.safety.enforcement import SafetyExecutionDenied

    with pytest.raises(SafetyExecutionDenied):
        SafetyEnforcement(safety).require_execution_allowed("business-1")

    service.begin_investigation(founder, incident_id)
    service.resolve_incident(
        founder,
        incident_id,
        notes="Emergency cause investigated and corrected.",
    )
    service.verify_fix(
        founder,
        incident_id,
        notes="Corrective action independently verified.",
    )
    service.authorize_resume(founder, incident_id)
    service.resume_control(founder, control.control_id)

    access = BusinessAccessService(db)

    with pytest.raises(BusinessAccessDenied):
        access.require_execution("business-1")

    state = SQLiteCommercialStateRepository(db).get("business-1")
    assert state is not None
    assert state.status is CommercialStatus.EXPIRED


def test_safety_recovery_cannot_restore_suspended_commercial_access(tmp_path):
    """Releasing an emergency halt must never restore suspended access."""
    from app.commercial.state import CommercialStatus, BusinessCommercialState
    from app.persistence.commercial_state_repository import (
        SQLiteCommercialStateRepository,
    )
    from app.web.access import BusinessAccessDenied, BusinessAccessService

    db, service, _, safety, founder, _ = _setup(tmp_path)

    SQLiteCommercialStateRepository(db).save(
        BusinessCommercialState(
            "business-1",
            CommercialStatus.SUSPENDED,
        )
    )

    control = service.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        reason="D5 commercial-boundary attack test.",
    )

    incident_id = control.incident_id
    assert incident_id is not None

    service.begin_investigation(founder, incident_id)
    service.resolve_incident(
        founder,
        incident_id,
        notes="Emergency cause investigated and corrected.",
    )
    service.verify_fix(
        founder,
        incident_id,
        notes="Corrective action independently verified.",
    )
    service.authorize_resume(founder, incident_id)
    service.resume_control(founder, control.control_id)

    access = BusinessAccessService(db)

    with pytest.raises(BusinessAccessDenied):
        access.require_execution("business-1")

    state = SQLiteCommercialStateRepository(db).get("business-1")
    assert state is not None
    assert state.status is CommercialStatus.SUSPENDED


def test_non_founder_cannot_halt(tmp_path):
    (
        _,
        service,
        _,
        _,
        _,
        user,
    ) = _setup(tmp_path)

    with pytest.raises(PermissionError):
        service.halt(
            user,
            scope=SafetyControlScope.GLOBAL,
            target="platform",
            reason="Unauthorized halt",
        )


def test_resume_cannot_skip_investigation(tmp_path):
    (
        _,
        service,
        _,
        _,
        founder,
        _,
    ) = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency halt",
    )

    with pytest.raises(SafetyControlError):
        service.resume_control(
            founder,
            control.control_id,
        )


def test_resume_cannot_skip_verification(tmp_path):
    (
        _,
        service,
        _,
        _,
        founder,
        _,
    ) = _setup(tmp_path)

    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency halt",
    )

    service.begin_investigation(
        founder,
        control.incident_id,
    )

    service.resolve_incident(
        founder,
        control.incident_id,
        notes="Fix completed.",
    )

    with pytest.raises(SafetyControlError):
        service.resume_control(
            founder,
            control.control_id,
        )


def test_active_founder_can_recover_control_created_by_another_founder(tmp_path):
    (
        db,
        service,
        _,
        _safety,
        founder,
        _,
    ) = _setup(tmp_path)

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            (
                "founder-2",
                "Founder Two",
                "founder2@example.test",
            ),
        )
        connection.execute(
            """
            INSERT INTO platform_founders(user_id, active)
            VALUES (?, 1)
            """,
            ("founder-2",),
        )

    other = AuthenticatedPrincipal(
        user_id="founder-2",
        business_id="platform",
        role=UserRole.OWNER,
        session_id="founder-two-session",
    )

    # Founder 1 creates the emergency control.
    control = service.halt(
        founder,
        scope=SafetyControlScope.GLOBAL,
        target="platform",
        reason="Emergency halt",
    )

    incident = service.begin_investigation(
        other,
        control.incident_id,
    )

    assert incident.status is SafetyIncidentStatus.INVESTIGATING
    assert incident.created_by_user_id == "founder-1"

    incident = service.resolve_incident(
        other,
        control.incident_id,
        notes="Fixed by Founder Two.",
    )

    assert incident.status is SafetyIncidentStatus.RESOLVED
    assert incident.resolved_by_user_id == "founder-2"

    incident = service.verify_fix(
        other,
        control.incident_id,
        notes="Verified by Founder Two.",
    )

    assert incident.status is SafetyIncidentStatus.VERIFIED
    assert incident.verified_by_user_id == "founder-2"

    incident = service.authorize_resume(
        other,
        control.incident_id,
    )

    assert incident.status is SafetyIncidentStatus.RESUME_AUTHORIZED
    assert incident.resume_authorized_by_user_id == "founder-2"

    resumed_control = service.resume_control(
        other,
        control.control_id,
    )

    assert resumed_control.state is SafetyControlState.ACTIVE
    assert resumed_control.activated_by_user_id == "founder-1"
    assert resumed_control.resumed_by_user_id == "founder-2"

    incident = service.close_incident(
        other,
        control.incident_id,
    )

    assert incident.status is SafetyIncidentStatus.CLOSED
    assert incident.closed_by_user_id == "founder-2"

    # The original creator remains permanently recorded.
    stored_incident = service._safety.get_incident(control.incident_id)
    stored_control = service._safety.get_control(control.control_id)

    assert stored_incident is not None
    assert stored_control is not None

    assert stored_incident.created_by_user_id == "founder-1"
    assert stored_incident.resolved_by_user_id == "founder-2"
    assert stored_incident.verified_by_user_id == "founder-2"
    assert stored_incident.resume_authorized_by_user_id == "founder-2"
    assert stored_incident.closed_by_user_id == "founder-2"

    assert stored_control.activated_by_user_id == "founder-1"
    assert stored_control.resumed_by_user_id == "founder-2"
def test_founder_action_creates_audit_event(tmp_path):
    (
        _,
        service,
        events,
        _,
        founder,
        _,
    ) = _setup(tmp_path)

    service.halt(
        founder,
        scope=SafetyControlScope.BUSINESS,
        target="business-1",
        reason="Business containment",
    )

    recent = events.list_recent(limit=10)

    assert any(
        event.action == "safety.halt"
        and event.user_id == "founder-1"
        and event.actor_type.value == "founder"
        and event.business_id == "business-1"
        for event in recent
    )
