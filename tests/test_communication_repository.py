from datetime import datetime, timezone
from hashlib import sha256

import pytest

from app.owner.attention_events import SQLiteAttentionEventRepository
from app.persistence.communication_repository import (
    SQLiteCommunicationRepository,
)
from test_web_application import make_app, signup, login


def setup_owner(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]

    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal

    app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )

    database = app.extensions["assistant_database"]
    events = SQLiteAttentionEventRepository(database)
    communications = SQLiteCommunicationRepository(database)

    now = datetime.now(timezone.utc).isoformat()
    event = events.create(
        business_id,
        principal.user_id,
        idempotency_key="communication-test",
        event_type="communication_test",
        severity="important",
        title="Communication test",
        details="Testing authorised delivery.",
        decision=type("Decision", (), {
            "action": "deliver",
            "reason": "Test",
            "evaluated_at": now,
            "local_time": "08:00",
            "quiet_hours_active": False,
            "deliver_after": None,
        })(),
    )

    return database, communications, business_id, principal.user_id, event


def register_endpoint(repository, business_id, user_id, endpoint_id="endpoint-1"):
    value = "+27820000000"
    repository.register_endpoint(
        endpoint_id=endpoint_id,
        business_id=business_id,
        user_id=user_id,
        channel="sms",
        encrypted_endpoint=b"encrypted-test-value",
        key_version="test-v1",
        fingerprint=sha256(value.encode()).hexdigest(),
        verified_at="2026-11-11T10:00:00+00:00",
        consent_granted_at="2026-11-11T10:00:00+00:00",
    )
    return endpoint_id


def test_migration_creates_communication_tables(tmp_path):
    database, _, _, _, _ = setup_owner(tmp_path)

    with database.connection() as db:
        tables = {
            row["name"]
            for row in db.execute("""
                SELECT name FROM sqlite_master WHERE type = 'table'
            """).fetchall()
        }

    assert "owner_communication_channels" in tables
    assert "tenant_communication_identities" in tables
    assert "attention_delivery_attempts" in tables
    with database.connection() as db:
        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(attention_delivery_attempts)"
            ).fetchall()
        }
        version = db.execute(
            "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
        ).fetchone()["value"]
    assert "claimed_by" in columns
    assert int(version) == 31


def test_endpoint_is_listed_only_while_authorised(tmp_path):
    _, repository, business_id, user_id, _ = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    endpoints = repository.list_enabled_endpoints(
        business_id=business_id,
        user_id=user_id,
    )

    assert len(endpoints) == 1
    assert endpoints[0]["endpoint_id"] == endpoint_id
    assert endpoints[0]["encrypted_endpoint"] == b"encrypted-test-value"

    assert repository.revoke_endpoint(
        endpoint_id=endpoint_id,
        business_id=business_id,
        user_id=user_id,
    )
    assert repository.list_enabled_endpoints(
        business_id=business_id,
        user_id=user_id,
    ) == []


def test_revocation_cannot_be_performed_by_another_tenant(tmp_path):
    _, repository, business_id, user_id, _ = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    assert not repository.revoke_endpoint(
        endpoint_id=endpoint_id,
        business_id=business_id,
        user_id="another-user",
    )
    assert len(repository.list_enabled_endpoints(
        business_id=business_id,
        user_id=user_id,
    )) == 1


def test_delivery_queue_is_idempotent_and_tenant_scoped(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    assert repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
    ) == 1

    assert repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
    ) == 0

    with pytest.raises(PermissionError):
        repository.queue_delivery(
            event_id=event.event_id,
            business_id=business_id,
            user_id="another-user",
            endpoint_ids=[endpoint_id],
        )


def test_delivery_requires_a_verified_consented_endpoint(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)

    assert repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=["does-not-exist"],
    ) == 0


def test_claim_and_confirmed_delivery(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
    )

    claimed = repository.claim_due_attempts(
        business_id=business_id,
        user_id=user_id,
        worker_id="worker-test",
    )

    assert len(claimed) == 1
    attempt = claimed[0]
    assert attempt["status"] == "claimed"
    assert attempt["attempts"] == 1
    assert attempt["claim_token"]
    assert attempt["claimed_by"] == "worker-test"

    assert repository.finish_attempt(
        delivery_id=attempt["delivery_id"],
        claim_token=attempt["claim_token"],
        outcome="delivered",
        provider_reference="provider-reference-123",
    )

    with repository.database.connection() as db:
        saved = db.execute(
            "SELECT * FROM attention_delivery_attempts WHERE delivery_id = ?",
            (attempt["delivery_id"],),
        ).fetchone()

    assert saved["status"] == "delivered"
    assert saved["provider_reference"] == "provider-reference-123"
    assert saved["delivered_at"] is not None
    assert saved["claim_token"] is None
    assert saved["claimed_by"] is None


def test_definite_failure_can_be_scheduled_for_retry(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
        max_attempts=3,
    )

    attempt = repository.claim_due_attempts(
        business_id=business_id,
        user_id=user_id,
        worker_id="worker-test",
    )[0]

    retry_at = "2099-01-01T00:00:00+00:00"
    assert repository.finish_attempt(
        delivery_id=attempt["delivery_id"],
        claim_token=attempt["claim_token"],
        outcome="failed",
        failure_reason="provider_rejected",
        retry_at=retry_at,
    )

    with repository.database.connection() as db:
        saved = db.execute(
            "SELECT * FROM attention_delivery_attempts WHERE delivery_id = ?",
            (attempt["delivery_id"],),
        ).fetchone()

    assert saved["status"] == "queued"
    assert saved["attempts"] == 1
    assert saved["next_attempt_at"] == retry_at
    assert saved["claim_token"] is None
    assert saved["claimed_by"] is None


def test_unknown_provider_outcome_is_not_retried(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
    )

    attempt = repository.claim_due_attempts(
        business_id=business_id,
        user_id=user_id,
        worker_id="worker-test",
    )[0]

    assert repository.finish_attempt(
        delivery_id=attempt["delivery_id"],
        claim_token=attempt["claim_token"],
        outcome="unknown",
        failure_reason="provider_outcome_unknown",
    )

    assert repository.claim_due_attempts(
        business_id=business_id,
        user_id=user_id,
        worker_id="worker-test",
    ) == []


def test_expired_claim_cannot_be_completed(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)
    endpoint_id = register_endpoint(repository, business_id, user_id)

    repository.queue_delivery(
        event_id=event.event_id,
        business_id=business_id,
        user_id=user_id,
        endpoint_ids=[endpoint_id],
        next_attempt_at="2019-12-31T00:00:00+00:00",
    )

    claimed = repository.claim_due_attempts(
        business_id=business_id,
        user_id=user_id,
        worker_id="worker-test",
        lease_seconds=5,
        now="2020-01-01T00:00:00+00:00",
    )[0]

    assert claimed["claimed_by"] == "worker-test"
    assert repository.recover_expired_claims(
        business_id=business_id,
        user_id=user_id,
        now="2020-01-01T00:00:06+00:00",
    ) == 1

    with repository.database.connection() as db:
        saved = db.execute(
            "SELECT * FROM attention_delivery_attempts WHERE delivery_id = ?",
            (claimed["delivery_id"],),
        ).fetchone()

    assert saved["status"] == "unknown"
    assert saved["failure_reason"] == "claim_expired_outcome_unknown"
    assert saved["claim_token"] is None
    assert saved["lease_expires_at"] is None
    assert saved["claimed_by"] is None
    assert not repository.finish_attempt(
        delivery_id=claimed["delivery_id"],
        claim_token=claimed["claim_token"],
        outcome="delivered",
        provider_reference="late-result",
    )
    assert repository.recover_expired_claims(
        business_id=business_id,
        user_id=user_id,
        now="2020-01-01T00:00:10+00:00",
    ) == 0


def test_duplicate_endpoint_ids_are_rejected(tmp_path):
    _, repository, business_id, user_id, event = setup_owner(tmp_path)

    with pytest.raises(ValueError):
        repository.queue_delivery(
            event_id=event.event_id,
            business_id=business_id,
            user_id=user_id,
            endpoint_ids=["same", "same"],
        )
