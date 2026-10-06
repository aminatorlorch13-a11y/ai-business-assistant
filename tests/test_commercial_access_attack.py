from datetime import datetime, timedelta, timezone

import pytest

from app.commercial.access import BusinessAccessDenied, BusinessAccessService
from app.commercial.state import BusinessCommercialState, CommercialStatus
from app.commercial.trial import BusinessTrial
from app.persistence.commercial_state_repository import (
    SQLiteCommercialStateRepository,
)
from app.persistence.trial_repository import SQLiteTrialRepository


BUSINESS_ONE = "business-001"
BUSINESS_TWO = "business-002"

NOW = datetime(2026, 9, 20, 15, 30, tzinfo=timezone.utc)


def _make_database(tmp_path):
    from app.persistence.database import SQLiteDatabase
    from app.models.business import Business
    from app.persistence.business_repository import SQLiteBusinessRepository

    database = SQLiteDatabase(str(tmp_path / "commercial-access.sqlite3"))
    database.initialize()

    repository = SQLiteBusinessRepository(database)
    repository.save(
        Business(
            BUSINESS_ONE,
            "Business One",
            "Owner One",
            "Assistant One",
            "female",
        )
    )
    repository.save(
        Business(
            BUSINESS_TWO,
            "Business Two",
            "Owner Two",
            "Assistant Two",
            "female",
        )
    )

    return database


def _save_state(database, business_id, status):
    SQLiteCommercialStateRepository(database).save(
        BusinessCommercialState(business_id, status)
    )


def _save_trial(database, business_id, started_at):
    SQLiteTrialRepository(database).save(
        BusinessTrial(business_id, started_at)
    )


def _clock():
    return NOW


def test_active_business_is_allowed_to_execute(tmp_path):
    database = _make_database(tmp_path)
    _save_state(database, BUSINESS_ONE, CommercialStatus.ACTIVE)

    access = BusinessAccessService(database, clock=_clock)

    resolved = access.require_execution(BUSINESS_ONE)

    assert resolved.business_id == BUSINESS_ONE
    assert resolved.status is CommercialStatus.ACTIVE
    assert resolved.allowed is True


def test_valid_trial_is_allowed_to_execute(tmp_path):
    database = _make_database(tmp_path)

    started_at = NOW - timedelta(days=6)
    _save_state(database, BUSINESS_ONE, CommercialStatus.TRIAL)
    _save_trial(database, BUSINESS_ONE, started_at)

    access = BusinessAccessService(database, clock=_clock)

    resolved = access.require_execution(BUSINESS_ONE)

    assert resolved.business_id == BUSINESS_ONE
    assert resolved.status is CommercialStatus.TRIAL
    assert resolved.allowed is True
    assert resolved.trial_ends_at == started_at + timedelta(days=7)


def test_trial_at_exact_expiry_is_denied(tmp_path):
    database = _make_database(tmp_path)

    started_at = NOW - timedelta(days=7)
    _save_state(database, BUSINESS_ONE, CommercialStatus.TRIAL)
    _save_trial(database, BUSINESS_ONE, started_at)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="trial has expired"):
        access.require_execution(BUSINESS_ONE)

    state = SQLiteCommercialStateRepository(database).get(BUSINESS_ONE)
    assert state is not None
    assert state.status is CommercialStatus.EXPIRED


def test_expired_trial_is_denied_and_state_is_persisted_as_expired(tmp_path):
    database = _make_database(tmp_path)

    started_at = NOW - timedelta(days=7, seconds=1)
    _save_state(database, BUSINESS_ONE, CommercialStatus.TRIAL)
    _save_trial(database, BUSINESS_ONE, started_at)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="trial has expired"):
        access.require_execution(BUSINESS_ONE)

    state = SQLiteCommercialStateRepository(database).get(BUSINESS_ONE)
    assert state is not None
    assert state.status is CommercialStatus.EXPIRED


def test_missing_trial_information_fails_closed_and_persists_expired_state(
    tmp_path,
):
    database = _make_database(tmp_path)
    _save_state(database, BUSINESS_ONE, CommercialStatus.TRIAL)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="Trial information is missing"):
        access.require_execution(BUSINESS_ONE)

    state = SQLiteCommercialStateRepository(database).get(BUSINESS_ONE)
    assert state is not None
    assert state.status is CommercialStatus.EXPIRED


def test_read_only_resolution_does_not_mutate_expired_trial_state(tmp_path):
    database = _make_database(tmp_path)

    started_at = NOW - timedelta(days=7, seconds=1)
    _save_state(database, BUSINESS_ONE, CommercialStatus.TRIAL)
    _save_trial(database, BUSINESS_ONE, started_at)

    access = BusinessAccessService(database, clock=_clock)
    resolved = access.resolve_read_only(BUSINESS_ONE)

    assert resolved.business_id == BUSINESS_ONE
    assert resolved.status is CommercialStatus.EXPIRED
    assert resolved.allowed is False
    assert resolved.reason == "The trial has expired."

    state = SQLiteCommercialStateRepository(database).get(BUSINESS_ONE)
    assert state is not None
    assert state.status is CommercialStatus.TRIAL
def test_suspended_business_cannot_execute(tmp_path):
    database = _make_database(tmp_path)
    _save_state(database, BUSINESS_ONE, CommercialStatus.SUSPENDED)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="suspended"):
        access.require_execution(BUSINESS_ONE)


def test_expired_business_cannot_execute(tmp_path):
    database = _make_database(tmp_path)
    _save_state(database, BUSINESS_ONE, CommercialStatus.EXPIRED)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="suspended"):
        access.require_execution(BUSINESS_ONE)


def test_missing_commercial_state_fails_closed(tmp_path):
    database = _make_database(tmp_path)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="commercial state is missing"):
        access.require_execution(BUSINESS_ONE)


def test_business_two_cannot_use_business_one_commercial_state(tmp_path):
    database = _make_database(tmp_path)
    _save_state(database, BUSINESS_ONE, CommercialStatus.ACTIVE)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises(BusinessAccessDenied, match="commercial state is missing"):
        access.require_execution(BUSINESS_TWO)


@pytest.mark.parametrize("business_id", ["", "   ", None, 123])
def test_invalid_business_id_fails_closed(tmp_path, business_id):
    database = _make_database(tmp_path)

    access = BusinessAccessService(database, clock=_clock)

    with pytest.raises((ValueError, TypeError)):
        access.require_execution(business_id)
