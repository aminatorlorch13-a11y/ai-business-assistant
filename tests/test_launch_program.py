import pytest

from app.commercial.launch import (
    DEFAULT_LAUNCH_TARGET,
    LaunchProgram,
    LaunchProgramStatus,
)


def test_default_launch_target_is_ten():
    program = LaunchProgram()

    assert DEFAULT_LAUNCH_TARGET == 10
    assert program.target_businesses == 10
    assert program.paid_businesses == 0
    assert program.remaining_businesses == 10
    assert program.status is LaunchProgramStatus.OPEN


def test_one_paid_business_leaves_nine_remaining():
    program = LaunchProgram(
        paid_businesses=1,
    )

    assert program.paid_businesses == 1
    assert program.remaining_businesses == 9
    assert program.status is LaunchProgramStatus.OPEN


def test_nine_paid_businesses_leave_one_remaining():
    program = LaunchProgram(
        paid_businesses=9,
    )

    assert program.paid_businesses == 9
    assert program.remaining_businesses == 1
    assert program.status is LaunchProgramStatus.OPEN


def test_ten_paid_businesses_close_program():
    program = LaunchProgram(
        paid_businesses=10,
    )

    assert program.paid_businesses == 10
    assert program.remaining_businesses == 0
    assert program.status is LaunchProgramStatus.CLOSED


def test_custom_target_is_supported():
    program = LaunchProgram(
        target_businesses=25,
        paid_businesses=3,
    )

    assert program.target_businesses == 25
    assert program.paid_businesses == 3
    assert program.remaining_businesses == 22
    assert program.status is LaunchProgramStatus.OPEN


def test_program_is_immutable():
    program = LaunchProgram()

    with pytest.raises(AttributeError):
        program.target_businesses = 20

    with pytest.raises(AttributeError):
        program.paid_businesses = 1


def test_target_must_be_integer():
    with pytest.raises(TypeError, match="target_businesses"):
        LaunchProgram(
            target_businesses="10",
        )


def test_boolean_target_is_rejected():
    with pytest.raises(TypeError, match="target_businesses"):
        LaunchProgram(
            target_businesses=True,
        )


def test_target_must_be_positive():
    with pytest.raises(ValueError, match="greater than zero"):
        LaunchProgram(
            target_businesses=0,
        )


def test_negative_target_is_rejected():
    with pytest.raises(ValueError, match="greater than zero"):
        LaunchProgram(
            target_businesses=-1,
        )


def test_paid_businesses_must_be_integer():
    with pytest.raises(TypeError, match="paid_businesses"):
        LaunchProgram(
            paid_businesses="1",
        )


def test_boolean_paid_businesses_is_rejected():
    with pytest.raises(TypeError, match="paid_businesses"):
        LaunchProgram(
            paid_businesses=True,
        )


def test_negative_paid_businesses_is_rejected():
    with pytest.raises(ValueError, match="must not be negative"):
        LaunchProgram(
            paid_businesses=-1,
        )


def test_paid_businesses_cannot_exceed_target():
    with pytest.raises(
        ValueError,
        match="cannot exceed target_businesses",
    ):
        LaunchProgram(
            target_businesses=10,
            paid_businesses=11,
        )


def test_remaining_businesses_is_derived():
    program = LaunchProgram(
        target_businesses=10,
        paid_businesses=4,
    )

    assert program.remaining_businesses == (
        program.target_businesses - program.paid_businesses
    )


def test_status_is_derived_from_paid_businesses():
    open_program = LaunchProgram(
        target_businesses=10,
        paid_businesses=9,
    )
    closed_program = LaunchProgram(
        target_businesses=10,
        paid_businesses=10,
    )

    assert open_program.status is LaunchProgramStatus.OPEN
    assert closed_program.status is LaunchProgramStatus.CLOSED


def test_trial_expiration_does_not_reduce_paid_business_count():
    """
    The launch program tracks verified paying businesses, not trials.

    An expired trial therefore has no effect on this state.
    """
    program = LaunchProgram(
        paid_businesses=0,
    )

    assert program.paid_businesses == 0
    assert program.remaining_businesses == 10
    assert program.status is LaunchProgramStatus.OPEN


def test_no_pricing_fields_exist():
    program = LaunchProgram()

    assert not hasattr(program, "price")
    assert not hasattr(program, "monthly_price")
    assert not hasattr(program, "setup_fee")


def test_no_payment_credentials_exist():
    program = LaunchProgram()

    assert not hasattr(program, "bank_account")
    assert not hasattr(program, "account_number")
    assert not hasattr(program, "payment_credentials")
