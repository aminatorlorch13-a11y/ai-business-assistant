from datetime import datetime, timezone

import pytest

from app.platform.events import (
    PlatformEvent,
    PlatformEventActorType,
    PlatformEventChannel,
    PlatformEventOutcome,
)


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_event(**overrides):
    values = {
        "event_id": "event-1",
        "occurred_at": NOW,
        "event_type": "assistant.action",
        "business_id": "business-1",
        "user_id": "user-1",
        "channel": PlatformEventChannel.WEB,
        "actor_type": PlatformEventActorType.USER,
        "action": "send_message",
        "outcome": PlatformEventOutcome.SUCCESS,
        "correlation_id": "corr-1",
        "metadata": {"duration_ms": 120},
    }
    values.update(overrides)
    return PlatformEvent(**values)


def test_platform_event_accepts_valid_event():
    event = make_event()

    assert event.event_id == "event-1"
    assert event.business_id == "business-1"
    assert event.channel is PlatformEventChannel.WEB
    assert event.actor_type is PlatformEventActorType.USER
    assert event.outcome is PlatformEventOutcome.SUCCESS
    assert event.metadata == {"duration_ms": 120}


def test_platform_event_normalizes_timestamp_to_utc():
    value = datetime(
        2026,
        1,
        1,
        14,
        tzinfo=timezone.utc,
    )

    event = make_event(occurred_at=value)

    assert event.occurred_at == value


def test_platform_event_requires_timezone_aware_timestamp():
    with pytest.raises(ValueError):
        make_event(occurred_at=datetime(2026, 1, 1, 12))


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", ""),
        ("event_type", ""),
        ("action", ""),
        ("correlation_id", ""),
    ],
)
def test_platform_event_rejects_empty_required_identifiers(field, value):
    with pytest.raises(ValueError):
        make_event(**{field: value})


def test_platform_event_rejects_invalid_channel():
    with pytest.raises(TypeError):
        make_event(channel="web")


def test_platform_event_rejects_invalid_actor_type():
    with pytest.raises(TypeError):
        make_event(actor_type="user")


def test_platform_event_rejects_invalid_outcome():
    with pytest.raises(TypeError):
        make_event(outcome="success")


def test_platform_event_rejects_non_mapping_metadata():
    with pytest.raises(TypeError):
        make_event(metadata=["not", "mapping"])


def test_platform_event_accepts_json_compatible_metadata():
    event = make_event(
        metadata={
            "count": 3,
            "enabled": True,
            "ratio": 1.5,
            "nothing": None,
            "items": ["a", 2, False],
            "nested": {"key": "value"},
        }
    )

    assert event.metadata["count"] == 3
    assert event.metadata["nested"]["key"] == "value"


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "secret",
        "token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "private_key",
    ],
)
def test_platform_event_rejects_sensitive_metadata_keys(key):
    with pytest.raises(ValueError):
        make_event(metadata={key: "sensitive-value"})


def test_platform_event_rejects_oversized_metadata():
    with pytest.raises(ValueError):
        make_event(metadata={"payload": "x" * 20_000})


def test_platform_event_rejects_excessive_metadata_depth():
    value = {"level": {"level": {"level": {"level": {"level": {"level": {"level": "too-deep"}}}}}}}

    with pytest.raises(ValueError):
        make_event(metadata=value)


def test_platform_event_metadata_is_not_mutable_through_original_mapping():
    metadata = {"operation": "send"}

    event = make_event(metadata=metadata)

    metadata["operation"] = "tampered"

    assert event.metadata["operation"] == "send"
