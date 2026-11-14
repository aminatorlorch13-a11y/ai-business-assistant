from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.owner.models import OwnerLifestylePreferences
from app.owner.attention_policy import OwnerAttentionPolicy


ZONE = ZoneInfo("Africa/Johannesburg")


def prefs(**changes):
    base = OwnerLifestylePreferences(
        business_id="business-1",
        user_id="owner-1",
        timezone="Africa/Johannesburg",
        wake_time="06:00",
        sleep_time="22:00",
        quiet_start="21:00",
        quiet_end="07:00",
        briefing_enabled=True,
        briefing_time="07:00",
        critical_alerts_during_quiet=True,
    )
    return replace(base, **changes)


def at(hour, minute=0, day=10):
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


def test_critical_event_interrupts_during_quiet_hours_when_allowed():
    result = OwnerAttentionPolicy.evaluate(prefs(), "critical", at(23))
    assert result.action == "interrupt"
    assert result.quiet_hours_active is True


def test_critical_event_is_deferred_when_owner_disables_quiet_override():
    result = OwnerAttentionPolicy.evaluate(
        prefs(critical_alerts_during_quiet=False), "critical", at(23)
    )
    assert result.action == "defer"
    assert result.deliver_after.startswith("2026-11-11T07:00:00")


def test_important_event_waits_until_quiet_period_ends():
    result = OwnerAttentionPolicy.evaluate(prefs(), "important", at(23))
    assert result.action == "defer"
    assert result.deliver_after.startswith("2026-11-11T07:00:00")


def test_important_event_delivers_outside_quiet_hours():
    result = OwnerAttentionPolicy.evaluate(prefs(), "important", at(10))
    assert result.action == "deliver"
    assert result.quiet_hours_active is False


def test_routine_event_is_reserved_for_next_briefing():
    result = OwnerAttentionPolicy.evaluate(prefs(), "routine", at(10))
    assert result.action == "briefing"
    assert result.deliver_after.startswith("2026-11-11T07:00:00")


def test_routine_event_uses_todays_briefing_if_not_yet_due():
    result = OwnerAttentionPolicy.evaluate(prefs(), "routine", at(6, 30))
    assert result.action == "briefing"
    assert result.deliver_after.startswith("2026-11-10T07:00:00")


def test_routine_event_is_queued_when_briefings_are_disabled():
    result = OwnerAttentionPolicy.evaluate(
        prefs(briefing_enabled=False), "routine", at(10)
    )
    assert result.action == "queue"
    assert result.deliver_after is None


def test_sleep_window_is_respected_even_without_custom_quiet_hours():
    result = OwnerAttentionPolicy.evaluate(
        prefs(quiet_start=None, quiet_end=None), "important", at(23)
    )
    assert result.action == "defer"
    assert result.deliver_after.startswith("2026-11-11T06:00:00")


def test_overnight_quiet_window_is_respected():
    result = OwnerAttentionPolicy.evaluate(
        prefs(sleep_time=None, wake_time=None), "important", at(2)
    )
    assert result.action == "defer"
    assert result.deliver_after.startswith("2026-11-10T07:00:00")


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        OwnerAttentionPolicy.evaluate(
            prefs(), "important", datetime(2026, 11, 10, 10)
        )


def test_unknown_severity_is_rejected():
    with pytest.raises(ValueError):
        OwnerAttentionPolicy.evaluate(prefs(), "urgent", at(10))
