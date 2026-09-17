import pytest

from app.automation.event import AutomationEvent


def make_event(payload=None):
    return AutomationEvent(
        business_id="business-001",
        event_type="email_received",
        payload={} if payload is None else payload,
    )


def test_event_accepts_valid_input():
    event = make_event(
        {
            "subject": "Customer inquiry",
            "sender": "customer@example.com",
        }
    )

    assert event.business_id == "business-001"
    assert event.event_type == "email_received"
    assert event.payload["subject"] == "Customer inquiry"
    assert event.payload["sender"] == "customer@example.com"


@pytest.mark.parametrize(
    "business_id",
    ["", "   ", None, 123],
)
def test_event_rejects_invalid_business_id(business_id):
    with pytest.raises((ValueError, TypeError), match="business_id"):
        AutomationEvent(
            business_id=business_id,
            event_type="email_received",
            payload={},
        )


@pytest.mark.parametrize(
    "event_type",
    ["", "   ", None, "unsupported"],
)
def test_event_rejects_invalid_event_type(event_type):
    with pytest.raises((ValueError, TypeError), match="event_type"):
        AutomationEvent(
            business_id="business-001",
            event_type=event_type,
            payload={},
        )


@pytest.mark.parametrize(
    "event_type",
    [
        "email_received",
        "form_submitted",
        "order_received",
        "appointment_created",
        "reminder_due",
    ],
)
def test_event_accepts_supported_event_types(event_type):
    event = AutomationEvent(
        business_id="business-001",
        event_type=event_type,
        payload={},
    )

    assert event.event_type == event_type


@pytest.mark.parametrize(
    "payload",
    [None, [], "invalid", 123],
)
def test_event_rejects_non_mapping_payload(payload):
    with pytest.raises(TypeError, match="payload"):
        AutomationEvent(
            business_id="business-001",
            event_type="email_received",
            payload=payload,
        )


def test_event_payload_is_immutable():
    event = make_event({"subject": "Original"})

    with pytest.raises(TypeError):
        event.payload["subject"] = "Tampered"


def test_event_payload_is_snapshot_of_input():
    payload = {"subject": "Original"}

    event = make_event(payload)

    payload["subject"] = "Changed outside event"

    assert event.payload["subject"] == "Original"


def test_event_is_immutable():
    event = make_event()

    with pytest.raises(AttributeError):
        event.business_id = "business-999"


def test_event_deeply_snapshots_nested_payload():
    payload = {
        "customer": {
            "name": "Original",
            "tags": ["lead", "priority"],
        }
    }

    event = AutomationEvent(
        business_id="business-001",
        event_type="email_received",
        payload=payload,
    )

    payload["customer"]["name"] = "Tampered"
    payload["customer"]["tags"].append("attacker")

    assert event.payload["customer"]["name"] == "Original"
    assert event.payload["customer"]["tags"] == ("lead", "priority")


def test_event_rejects_nested_mapping_mutation():
    event = AutomationEvent(
        business_id="business-001",
        event_type="email_received",
        payload={
            "customer": {
                "name": "Original",
            }
        },
    )

    with pytest.raises(TypeError):
        event.payload["customer"]["name"] = "Tampered"


def test_event_rejects_nested_list_mutation():
    event = AutomationEvent(
        business_id="business-001",
        event_type="email_received",
        payload={
            "tags": ["lead", "priority"],
        },
    )

    with pytest.raises(AttributeError):
        event.payload["tags"].append("tampered")
