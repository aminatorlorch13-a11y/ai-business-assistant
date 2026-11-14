from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.owner.attention_events import SQLiteAttentionEventRepository
from app.owner.attention_worker import (
    AttentionDeliveryTarget,
    AttentionWorker,
)
from app.whatsapp.provider import (
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)
from test_web_application import make_app, signup, login


class SuccessfulProvider:
    def __init__(self):
        self.messages = []

    def send_text(self, provider_account_id, recipient, text):
        self.messages.append((provider_account_id, recipient, text))
        return "provider-message-123"


class RejectedProvider:
    def send_text(self, provider_account_id, recipient, text):
        raise WhatsAppProviderError("Provider rejected message")


class UnknownProvider:
    def send_text(self, provider_account_id, recipient, text):
        raise WhatsAppProviderOutcomeUnknown("Connection lost after sending")


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

    # Initialise the real owner preferences required by the
    # attention_events foreign key.
    app.extensions["assistant_owner_lifestyle"].get_preferences(
        principal, business_id
    )

    repository = SQLiteAttentionEventRepository(
        app.extensions["assistant_database"]
    )

    target = AttentionDeliveryTarget(
        business_id=business_id,
        user_id=principal.user_id,
        provider_account_id="configured-provider-account",
        recipient="+27820000000",
    )

    return repository, target


def create_event(repository, target, *, action="deliver", key="worker-test"):
    now = datetime.now(timezone.utc).isoformat()
    decision = SimpleNamespace(
        action=action,
        reason="Worker test",
        evaluated_at=now,
        local_time="08:00",
        quiet_hours_active=False,
        deliver_after=None,
    )

    return repository.create(
        target.business_id,
        target.user_id,
        idempotency_key=key,
        event_type="worker_test",
        severity="important",
        title="Test attention event",
        details="This is a worker delivery test.",
        decision=decision,
    )


def test_worker_confirms_delivery_only_after_provider_confirmation(tmp_path):
    repository, target = setup_owner(tmp_path)
    event = create_event(repository, target)
    provider = SuccessfulProvider()

    worker = AttentionWorker(repository, provider, target)
    result = worker.run_once()

    saved = repository.get(target.business_id, target.user_id, event.event_id)

    assert result.claimed == 1
    assert result.delivered == 1
    assert result.failed == 0
    assert saved.status == "delivered"
    assert saved.provider_message_id == "provider-message-123"
    assert saved.attempts == 1
    assert len(provider.messages) == 1
    assert provider.messages[0][1] == target.recipient


def test_worker_schedules_retry_after_definite_provider_rejection(tmp_path):
    repository, target = setup_owner(tmp_path)
    event = create_event(repository, target, key="rejected-event")

    worker = AttentionWorker(
        repository,
        RejectedProvider(),
        target,
        base_retry_seconds=60,
    )
    result = worker.run_once()

    saved = repository.get(target.business_id, target.user_id, event.event_id)

    assert result.retry_scheduled == 1
    assert result.failed == 0
    assert saved.status in {"queued", "deferred", "briefing"}
    assert saved.attempts == 1
    assert saved.retry_after is not None
    assert saved.claim_token is None
    assert "provider_rejected" in saved.failure_reason


def test_worker_quarantines_unknown_provider_outcome_without_retry(tmp_path):
    repository, target = setup_owner(tmp_path)
    event = create_event(repository, target, key="unknown-event")

    worker = AttentionWorker(repository, UnknownProvider(), target)
    result = worker.run_once()

    saved = repository.get(target.business_id, target.user_id, event.event_id)

    assert result.failed == 1
    assert result.retry_scheduled == 0
    assert saved.status == "failed"
    assert saved.attempts == 1
    assert saved.claim_token is None
    assert "manual_reconciliation_required" in saved.failure_reason


def test_worker_does_not_send_briefing_events_as_direct_alerts(tmp_path):
    repository, target = setup_owner(tmp_path)

    direct = create_event(repository, target, key="direct-event")
    briefing = create_event(
        repository, target, action="briefing", key="briefing-event"
    )

    provider = SuccessfulProvider()
    worker = AttentionWorker(repository, provider, target)
    result = worker.run_once()

    direct_saved = repository.get(
        target.business_id, target.user_id, direct.event_id
    )
    briefing_saved = repository.get(
        target.business_id, target.user_id, briefing.event_id
    )

    assert result.claimed == 1
    assert result.delivered == 1
    assert len(provider.messages) == 1
    assert direct_saved.status == "delivered"
    assert briefing_saved.status == "briefing"
    assert briefing_saved.attempts == 0
    assert briefing_saved.claim_token is None


def test_worker_requires_explicit_delivery_target():
    with pytest.raises(ValueError):
        AttentionWorker(object(), SuccessfulProvider(), None)
