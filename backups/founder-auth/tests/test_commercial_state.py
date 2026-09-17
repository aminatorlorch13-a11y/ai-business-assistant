import pytest

from app.commercial.state import (
    BusinessCommercialState,
    CommercialStatus,
)


def test_all_commercial_statuses_are_stable():
    assert CommercialStatus.TRIAL.value == "trial"
    assert CommercialStatus.ACTIVE.value == "active"
    assert CommercialStatus.EXPIRED.value == "expired"
    assert CommercialStatus.SUSPENDED.value == "suspended"


@pytest.mark.parametrize(
    "status",
    list(CommercialStatus),
)
def test_valid_commercial_state(status):
    state = BusinessCommercialState(
        business_id="business-001",
        status=status,
    )

    assert state.business_id == "business-001"
    assert state.status is status


def test_commercial_state_is_immutable():
    state = BusinessCommercialState(
        business_id="business-001",
        status=CommercialStatus.TRIAL,
    )

    with pytest.raises(AttributeError):
        state.business_id = "business-002"

    with pytest.raises(AttributeError):
        state.status = CommercialStatus.ACTIVE


def test_business_id_must_be_string():
    with pytest.raises(TypeError, match="business_id"):
        BusinessCommercialState(
            business_id=123,
            status=CommercialStatus.TRIAL,
        )


def test_business_id_must_not_be_empty():
    with pytest.raises(ValueError, match="business_id"):
        BusinessCommercialState(
            business_id="   ",
            status=CommercialStatus.TRIAL,
        )


def test_status_must_be_commercial_status():
    with pytest.raises(TypeError, match="CommercialStatus"):
        BusinessCommercialState(
            business_id="business-001",
            status="trial",
        )


def test_state_does_not_contain_pricing():
    state = BusinessCommercialState(
        business_id="business-001",
        status=CommercialStatus.ACTIVE,
    )

    assert not hasattr(state, "price")
    assert not hasattr(state, "monthly_price")
    assert not hasattr(state, "setup_fee")
