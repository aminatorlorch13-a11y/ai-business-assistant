from types import SimpleNamespace
from datetime import datetime

import pytest

from app.identity.models import BusinessMembership, UserRole
from app.models.business import Business
from app.owner.attention_events import SQLiteAttentionEventRepository
from app.owner.attention_service import OwnerAttentionService
from app.owner.models import OwnerLifestylePreferences
from app.owner.repository import SQLiteOwnerLifestyleRepository
from app.owner.service import OwnerLifestyleService
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.user_repository import SQLiteUserRepository, User


def make_environment(tmp_path):
    database = SQLiteDatabase(str(tmp_path / "attention.sqlite3"))
    database.initialize()

    users = SQLiteUserRepository(database)
    businesses = SQLiteBusinessRepository(database)
    memberships = SQLiteMembershipRepository(database)

    users.save(User("user-1", "Owner", "owner@example.test"))
    businesses.save(
        Business(
            "business-1",
            "Test Business",
            "Owner",
            "Assistant",
            "female",
        )
    )
    memberships.save(
        BusinessMembership("user-1", "business-1", UserRole.OWNER)
    )

    lifestyle_repository = SQLiteOwnerLifestyleRepository(database)
    lifestyle_service = OwnerLifestyleService(
        lifestyle_repository,
        memberships,
    )

    event_repository = SQLiteAttentionEventRepository(database)
    attention_service = OwnerAttentionService(
        lifestyle_service,
        event_repository,
    )

    principal = SimpleNamespace(
        user_id="user-1",
        business_id="business-1",
    )

    return (
        database,
        lifestyle_repository,
        event_repository,
        attention_service,
        principal,
    )


def ingest(service, principal):
    return service.ingest(
        principal,
        "business-1",
        idempotency_key="whatsapp:message-001",
        event_type="customer.message_received",
        severity="important",
        title="New customer message",
        details="A customer sent a WhatsApp message.",
        payload={"source": "whatsapp", "message_id": "message-001"},
        now=datetime.fromisoformat("2026-11-10T12:00:00+02:00"),
    )


def test_real_owner_service_ingests_and_persists_event(tmp_path):
    _, preferences, events, service, principal = make_environment(tmp_path)

    created = ingest(service, principal)
    stored = events.get("business-1", "user-1", created.event_id)

    assert stored is not None
    assert stored.event_id == created.event_id
    assert stored.event_type == "customer.message_received"
    assert stored.payload == {
        "source": "whatsapp",
        "message_id": "message-001",
    }
    assert stored.action == "deliver"
    assert stored.status == "queued"

    assert preferences.get("business-1", "user-1") is not None


def test_real_sqlite_ingestion_is_idempotent(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    first = ingest(service, principal)
    second = ingest(service, principal)

    assert first.event_id == second.event_id
    assert len(events.list_events("business-1", "user-1")) == 1


def test_real_membership_authorization_rejects_non_member(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    unauthorized = SimpleNamespace(
        user_id="user-2",
        business_id="business-1",
    )

    with pytest.raises(PermissionError, match="membership"):
        ingest(service, unauthorized)

    assert events.list_events("business-1", "user-1") == []


def test_real_owner_service_rejects_business_context_mismatch(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    wrong_context = SimpleNamespace(
        user_id="user-1",
        business_id="business-2",
    )

    with pytest.raises(PermissionError, match="Business context"):
        ingest(service, wrong_context)

    assert events.list_events("business-1", "user-1") == []


def test_real_database_enforces_tenant_scoped_event_retrieval(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    created = ingest(service, principal)

    assert events.get("business-1", "user-2", created.event_id) is None
    assert events.get("business-2", "user-1", created.event_id) is None


def test_real_owner_service_rejects_invalid_severity(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    with pytest.raises(ValueError):
        service.ingest(
            principal,
            "business-1",
            idempotency_key="invalid-severity",
            event_type="customer.message_received",
            severity="unknown",
            title="Invalid event",
            now=datetime.fromisoformat("2026-11-10T12:00:00+02:00"),
        )

    assert events.list_events("business-1", "user-1") == []


def test_real_owner_service_rejects_invalid_event_type(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    with pytest.raises(ValueError):
        service.ingest(
            principal,
            "business-1",
            idempotency_key="invalid-type",
            event_type="../unauthorized",
            severity="important",
            title="Invalid event",
            now=datetime.fromisoformat("2026-11-10T12:00:00+02:00"),
        )

    assert events.list_events("business-1", "user-1") == []


def test_real_owner_service_rejects_non_json_payload(tmp_path):
    _, _, events, service, principal = make_environment(tmp_path)

    with pytest.raises(ValueError):
        service.ingest(
            principal,
            "business-1",
            idempotency_key="invalid-payload",
            event_type="customer.message_received",
            severity="important",
            title="Invalid payload",
            payload={"invalid": object()},
            now=datetime.fromisoformat("2026-11-10T12:00:00+02:00"),
        )

    assert events.list_events("business-1", "user-1") == []
