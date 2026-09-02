from datetime import datetime, timedelta, timezone

import pytest

from app.commercial.trial import (
    TRIAL_DURATION_DAYS,
    BusinessTrial,
)


def make_start() -> datetime:
    return datetime(
        2026,
        9,
        1,
        10,
        0,
        tzinfo=timezone.utc,
    )


def test_trial_duration_is_seven_days():
    assert TRIAL_DURATION_DAYS == 7


def test_trial_calculates_exact_end_time():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert trial.ends_at == datetime(
        2026,
        9,
        8,
        10,
        0,
        tzinfo=timezone.utc,
    )


def test_trial_is_not_expired_before_end():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert trial.is_expired(
        trial.ends_at - timedelta(seconds=1)
    ) is False


def test_trial_expires_at_exact_end():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert trial.is_expired(trial.ends_at) is True


def test_trial_remains_expired_after_end():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert trial.is_expired(
        trial.ends_at + timedelta(seconds=1)
    ) is True


def test_trial_is_immutable():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    with pytest.raises(AttributeError):
        trial.business_id = "business-002"

    with pytest.raises(AttributeError):
        trial.started_at = make_start()


def test_business_id_must_be_string():
    with pytest.raises(TypeError, match="business_id"):
        BusinessTrial(
            business_id=123,
            started_at=make_start(),
        )


def test_business_id_must_not_be_empty():
    with pytest.raises(ValueError, match="business_id"):
        BusinessTrial(
            business_id="   ",
            started_at=make_start(),
        )


def test_started_at_must_be_datetime():
    with pytest.raises(TypeError, match="started_at"):
        BusinessTrial(
            business_id="business-001",
            started_at="2026-09-01",
        )


def test_started_at_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        BusinessTrial(
            business_id="business-001",
            started_at=datetime(2026, 9, 1, 10, 0),
        )


def test_expiration_check_requires_datetime():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    with pytest.raises(TypeError, match="datetime"):
        trial.is_expired("2026-09-08")


def test_expiration_check_requires_timezone_aware_datetime():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        trial.is_expired(
            datetime(2026, 9, 8, 10, 0)
        )


def test_different_timezone_can_represent_same_instant():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    equivalent_instant = datetime(
        2026,
        9,
        8,
        12,
        0,
        tzinfo=timezone(timedelta(hours=2)),
    )

    assert equivalent_instant == trial.ends_at
    assert trial.is_expired(equivalent_instant) is True


def test_trials_are_independent_per_business():
    business_one = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )
    business_two = BusinessTrial(
        business_id="business-002",
        started_at=make_start() + timedelta(days=1),
    )

    assert business_one.business_id != business_two.business_id
    assert business_one.ends_at != business_two.ends_at
    assert business_one.is_expired(
        business_one.ends_at
    ) is True
    assert business_two.is_expired(
        business_one.ends_at
    ) is False


def test_trial_contains_no_pricing():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert not hasattr(trial, "price")
    assert not hasattr(trial, "monthly_price")
    assert not hasattr(trial, "setup_fee")


def test_trial_contains_no_payment_state():
    trial = BusinessTrial(
        business_id="business-001",
        started_at=make_start(),
    )

    assert not hasattr(trial, "paid")
    assert not hasattr(trial, "payment_status")
    assert not hasattr(trial, "payment_id")
