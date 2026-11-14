from app.owner.communication_worker import CommunicationDeliveryWorker
from app.whatsapp.provider import (
    WhatsAppProviderError,
    WhatsAppProviderOutcomeUnknown,
)


class FakeRepository:
    def __init__(self, finish_result=True):
        self.finished = []
        self.finish_result = finish_result

    def finish_attempt(self, **kwargs):
        self.finished.append(kwargs)
        return self.finish_result


class FakeService:
    def _decrypt(self, encrypted, key_version):
        return {
            "encrypted-recipient": "+27123456789",
            "encrypted-account": "whatsapp-business-account",
        }[encrypted]


class FakeProvider:
    def __init__(self, result="wamid.test-123", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def send_text(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def make_worker(provider=None, finish_result=True):
    repository = FakeRepository(finish_result)
    provider = provider or FakeProvider()
    worker = CommunicationDeliveryWorker(
        repository=repository,
        communication_service=FakeService(),
        provider=provider,
        worker_id="test-communication-worker",
        poll_seconds=1,
    )
    worker._delivery_context = lambda attempt: {
        "delivery_id": "delivery-1",
        "event_id": "event-1",
        "business_id": "business-1",
        "user_id": "user-1",
        "endpoint_id": "endpoint-1",
        "channel": "whatsapp",
        "claim_token": "claim-1",
        "attempts": 1,
        "title": "Important update",
        "details": "Your report is ready.",
        "encrypted_endpoint": "encrypted-recipient",
        "endpoint_key_version": 1,
        "identity_provider": "meta_whatsapp",
        "encrypted_identity": "encrypted-account",
        "identity_key_version": 1,
        "identity_status": "active",
    }
    return worker, repository, provider


def make_attempt():
    return {
        "delivery_id": "delivery-1",
        "claim_token": "claim-1",
        "attempts": 1,
        "max_attempts": 3,
    }


def test_successful_delivery_records_provider_reference():
    worker, repository, provider = make_worker()

    assert worker._execute(make_attempt()) == "sent"
    assert len(provider.calls) == 1
    assert provider.calls[0]["provider_account_id"] == "whatsapp-business-account"
    assert provider.calls[0]["recipient"] == "+27123456789"
    assert "Important update" in provider.calls[0]["text"]
    assert repository.finished[-1]["outcome"] == "sent"
    assert repository.finished[-1]["provider_reference"] == "wamid.test-123"


def test_definite_provider_rejection_is_scheduled_for_retry():
    provider = FakeProvider(error=WhatsAppProviderError("Rejected"))
    worker, repository, _ = make_worker(provider=provider)

    assert worker._execute(make_attempt()) == "retry"
    assert repository.finished[-1]["outcome"] == "failed"
    assert repository.finished[-1]["retry_at"] is not None
    assert "provider_rejected" in repository.finished[-1]["failure_reason"]


def test_unknown_provider_outcome_is_never_automatically_retried():
    provider = FakeProvider(
        error=WhatsAppProviderOutcomeUnknown("Connection interrupted")
    )
    worker, repository, _ = make_worker(provider=provider)

    assert worker._execute(make_attempt()) == "unknown"
    assert repository.finished[-1]["outcome"] == "unknown"
    assert "retry_at" not in repository.finished[-1]


def test_missing_or_revoked_delivery_context_is_not_sent():
    worker, repository, provider = make_worker()
    worker._delivery_context = lambda attempt: None

    assert worker._execute(make_attempt()) == "failed"
    assert provider.calls == []
    assert repository.finished[-1]["outcome"] == "failed"


def test_inactive_tenant_identity_is_not_sent():
    worker, repository, provider = make_worker()
    original = worker._delivery_context

    def inactive_context(attempt):
        context = original(attempt)
        context["identity_status"] = "pending"
        return context

    worker._delivery_context = inactive_context

    assert worker._execute(make_attempt()) == "failed"
    assert provider.calls == []
    assert repository.finished[-1]["outcome"] == "failed"


def test_missing_provider_message_id_is_treated_as_unknown():
    provider = FakeProvider(result="")
    worker, repository, _ = make_worker(provider=provider)

    assert worker._execute(make_attempt()) == "unknown"
    assert repository.finished[-1]["outcome"] == "unknown"


def test_lost_claim_does_not_report_delivery_as_sent():
    worker, repository, _ = make_worker(finish_result=False)

    assert worker._execute(make_attempt()) == "claim_lost"
    assert repository.finished[-1]["outcome"] == "sent"


def test_message_content_is_bounded():
    worker, _, _ = make_worker()
    message = worker._message({"title": "Update", "details": "x" * 5000})

    assert len(message) == 4096
    assert message.startswith("Update")


def test_worker_start_and_stop_are_safe():
    worker, _, _ = make_worker()

    assert worker.start() is True
    assert worker.start() is False
    assert worker.stop(timeout=3) is True
    assert worker.stop(timeout=3) is True


def test_decryption_failure_is_recorded_as_preparation_failure():
    worker, repository, provider = make_worker()

    class BrokenService:
        def _decrypt(self, encrypted, key_version):
            raise ValueError("Decryption unavailable")

    worker.service = BrokenService()

    result = worker._execute(make_attempt())

    assert result == "failed"
    assert provider.calls == []
    assert repository.finished[-1]["outcome"] == "failed"
    assert repository.finished[-1]["failure_reason"].startswith(
        "delivery_preparation_failed:"
    )


def test_unexpected_provider_exception_is_recorded_as_unknown():
    class UnexpectedProvider:
        def send_text(self, **kwargs):
            raise RuntimeError("Connection interrupted after request")

    worker, repository, provider = make_worker(provider=UnexpectedProvider())

    result = worker._execute(make_attempt())

    assert result == "unknown"
    assert repository.finished[-1]["outcome"] == "unknown"
    assert repository.finished[-1]["failure_reason"] == (
        "unexpected_provider_outcome_unknown"
    )
