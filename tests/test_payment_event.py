from datetime import datetime, timezone

import pytest

from app.payment.event import PaymentProviderEvent


def make_event(**overrides):
    values = {
        "provider": "test_provider",
        "event_id": "evt_123",
        "event_type": "payment.completed",
        "payload": {
            "payment_id": "pay_123",
            "status": "completed",
        },
        "received_at": datetime(
            2026,
            9,
            2,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    }

    values.update(overrides)
    return PaymentProviderEvent(**values)


def test_valid_event_is_created():
    event = make_event()

    assert event.provider == "test_provider"
    assert event.event_id == "evt_123"
    assert event.event_type == "payment.completed"
    assert event.payload["payment_id"] == "pay_123"


def test_event_is_immutable():
    event = make_event()

    with pytest.raises(AttributeError):
        event.event_id = "attacker"


@pytest.mark.parametrize(
    "field",
    ["provider", "event_id", "event_type"],
)
def test_required_strings_must_be_non_empty(field):
    with pytest.raises(ValueError):
        make_event(**{field: "   "})


@pytest.mark.parametrize(
    "field",
    ["provider", "event_id", "event_type"],
)
def test_required_strings_must_be_strings(field):
    with pytest.raises(TypeError):
        make_event(**{field: 123})


def test_payload_must_be_mapping():
    with pytest.raises(TypeError):
        make_event(payload="not-a-mapping")


def test_payload_must_not_be_empty():
    with pytest.raises(ValueError):
        make_event(payload={})


def test_received_at_must_be_datetime():
    with pytest.raises(TypeError):
        make_event(received_at="2026-09-02T12:00:00Z")


def test_received_at_must_be_timezone_aware():
    with pytest.raises(ValueError):
        make_event(
            received_at=datetime(
                2026,
                9,
                2,
                12,
                0,
            )
        )
