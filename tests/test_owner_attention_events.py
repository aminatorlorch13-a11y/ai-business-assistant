import pytest

from app.owner.attention_policy import OwnerAttentionPolicy
from app.owner.attention_events import SQLiteAttentionEventRepository
from test_web_application import make_app, signup, login


def test_event_lifecycle_tracks_delivery_separately_from_acknowledgement(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal
    preferences = app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )

    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )
    decision = OwnerAttentionPolicy.evaluate(
        preferences, "important"
    )
    event = repository.create(
        business_id,
        principal.user_id,
        idempotency_key="order-delay-001",
        event_type="order_delay",
        severity="important",
        title="An order is delayed",
        decision=decision,
        details="Supplier delivery has been delayed.",
        payload={"order_id": "order-001"},
    )

    assert event.status == "queued"
    assert event.attempts == 0
    assert event.payload["order_id"] == "order-001"

    duplicate = repository.create(
        business_id,
        principal.user_id,
        idempotency_key="order-delay-001",
        event_type="order_delay",
        severity="important",
        title="Duplicate event",
        decision=decision,
    )
    assert duplicate.event_id == event.event_id
    assert duplicate.title == "An order is delayed"

    event = repository.record_attempt(
        business_id, principal.user_id, event.event_id
    )
    assert event.attempts == 1

    with pytest.raises(ValueError):
        repository.acknowledge(
            business_id, principal.user_id, event.event_id
        )

    event = repository.confirm_delivery(
        business_id, principal.user_id, event.event_id, "provider-msg-123"
    )
    assert event.status == "delivered"
    assert event.delivered_at is not None
    assert event.acknowledged_at is None

    event = repository.acknowledge(
        business_id, principal.user_id, event.event_id
    )
    assert event.status == "acknowledged"
    assert event.acknowledged_at is not None


def test_deferred_event_is_persisted_without_being_marked_delivered(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal
    preferences = app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )
    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )

    decision = OwnerAttentionPolicy.evaluate(
        preferences, "important"
    )
    event = repository.create(
        business_id,
        principal.user_id,
        idempotency_key="quiet-event-001",
        event_type="quiet_test",
        severity="important",
        title="Quiet-hours event",
        decision=decision,
    )

    assert event.status in {"queued", "deferred"}
    assert event.delivered_at is None
    assert event.acknowledged_at is None


def test_event_records_are_scoped_to_business_and_owner(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal
    preferences = app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )
    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )
    decision = OwnerAttentionPolicy.evaluate(preferences, "routine")

    event = repository.create(
        business_id, principal.user_id,
        idempotency_key="tenant-event-001",
        event_type="briefing_item",
        severity="routine",
        title="Briefing item",
        decision=decision,
    )

    assert repository.get("another-business", principal.user_id, event.event_id) is None
    assert repository.get(business_id, "another-user", event.event_id) is None


def test_failed_event_retains_reason_and_cannot_be_acknowledged(tmp_path):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)

    business_id = client.get("/api/me").get_json()["business_id"]
    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal
    preferences = app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )
    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )
    decision = OwnerAttentionPolicy.evaluate(preferences, "important")

    event = repository.create(
        business_id, principal.user_id,
        idempotency_key="failed-event-001",
        event_type="delivery_failure",
        severity="important",
        title="Delivery failed",
        decision=decision,
    )
    event = repository.mark_failed(
        business_id, principal.user_id, event.event_id, "Provider unavailable"
    )

    assert event.status == "failed"
    assert event.failure_reason == "Provider unavailable"
    with pytest.raises(ValueError):
        repository.acknowledge(business_id, principal.user_id, event.event_id)


def _make_claimable_event(tmp_path, key="lease-event-001"):
    app, _ = make_app(tmp_path)
    client = app.test_client()
    signup(client)
    login(client)
    business_id = client.get("/api/me").get_json()["business_id"]

    with client:
        client.get("/api/me")
        from flask import g
        principal = g.principal

    preferences = app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )
    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )
    decision = OwnerAttentionPolicy.evaluate(preferences, "important")
    event = repository.create(
        business_id,
        principal.user_id,
        idempotency_key=key,
        event_type="worker_test",
        severity="important",
        title="Worker lease test",
        decision=decision,
    )
    return repository, business_id, principal.user_id, event


def test_only_one_worker_can_claim_an_event(tmp_path):
    repository, business_id, user_id, event = _make_claimable_event(tmp_path)

    first = repository.claim_due_events(
        business_id, user_id, "worker-A", limit=5
    )
    second = repository.claim_due_events(
        business_id, user_id, "worker-B", limit=5
    )

    assert len(first) == 1
    assert first[0].event_id == event.event_id
    assert first[0].claimed_by == "worker-A"
    assert first[0].claim_token
    assert second == []


def test_expired_worker_cannot_complete_and_event_can_be_reclaimed(tmp_path):
    from datetime import datetime, timedelta, timezone

    repository, business_id, user_id, event = _make_claimable_event(tmp_path)
    start = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)

    first = repository.claim_due_events(
        business_id,
        user_id,
        "worker-A",
        now=start.isoformat(),
        lease_seconds=30,
    )[0]

    expired_time = (start + timedelta(seconds=31)).isoformat()

    with pytest.raises(ValueError):
        repository.complete_claim(
            business_id, user_id, event.event_id,
            first.claim_token, "stale-provider-message",
            now=expired_time,
        )

    released = repository.release_expired_claims(now=expired_time)
    assert released == 1

    second = repository.claim_due_events(
        business_id,
        user_id,
        "worker-B",
        now=expired_time,
    )[0]

    assert second.claim_token != first.claim_token
    assert second.claimed_by == "worker-B"

    completed = repository.complete_claim(
        business_id,
        user_id,
        event.event_id,
        second.claim_token,
        "provider-message-456",
        now=expired_time,
    )

    assert completed.status == "delivered"
    assert completed.claim_token is None
    assert completed.claimed_by is None


def test_claim_attempt_requires_valid_unexpired_lease(tmp_path):
    repository, business_id, user_id, event = _make_claimable_event(tmp_path)

    with pytest.raises(ValueError):
        repository.record_claim_attempt(
            business_id, user_id, event.event_id, "not-a-real-token"
        )

    claimed = repository.claim_due_events(
        business_id, user_id, "worker-A"
    )[0]

    attempted = repository.record_claim_attempt(
        business_id, user_id, event.event_id, claimed.claim_token
    )

    assert attempted.attempts == 1
    assert attempted.last_attempt_at is not None


def test_claiming_is_scoped_to_business_and_user(tmp_path):
    repository, business_id, user_id, event = _make_claimable_event(tmp_path)

    assert repository.claim_due_events(
        "another-business", user_id, "worker-A"
    ) == []

    assert repository.claim_due_events(
        business_id, "another-user", "worker-A"
    ) == []

    claimed = repository.claim_due_events(
        business_id, user_id, "worker-A"
    )

    assert len(claimed) == 1
    assert claimed[0].event_id == event.event_id
