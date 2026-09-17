import pytest

from app.assistant.action import AssistantAction
from app.services.appointment_operation import AppointmentOperation


def make_action(action_type: str) -> AssistantAction:
    return AssistantAction(
        business_id="business-001",
        action_type=action_type,
        target="appointment",
        instruction="Handle the appointment.",
    )


def test_create_appointment_action():
    operation = AppointmentOperation()

    assert operation.execute(make_action("create")) == (
        "Appointment creation requested."
    )


def test_update_appointment_action():
    operation = AppointmentOperation()

    assert operation.execute(make_action("update")) == (
        "Appointment update requested."
    )


def test_delete_appointment_action():
    operation = AppointmentOperation()

    assert operation.execute(make_action("delete")) == (
        "Appointment deletion requested."
    )


def test_none_appointment_action():
    operation = AppointmentOperation()

    assert operation.execute(make_action("none")) == (
        "No appointment operation required."
    )


def test_rejects_wrong_target():
    operation = AppointmentOperation()

    action = AssistantAction(
        business_id="business-001",
        action_type="create",
        target="invoice",
        instruction="Create an invoice.",
    )

    with pytest.raises(ValueError):
        operation.execute(action)
