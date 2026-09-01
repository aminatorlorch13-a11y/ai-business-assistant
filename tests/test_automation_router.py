import pytest

from app.automation.event import AutomationEvent
from app.automation.router import AutomationRouter


@pytest.mark.parametrize(
    ("event_type", "expected_module"),
    [
        ("email_received", "email_responder"),
        ("form_submitted", "intake_sorting"),
        ("order_received", "intake_sorting"),
        ("appointment_created", "reminders"),
        ("reminder_due", "reminders"),
    ],
)
def test_router_maps_event_to_module(
    event_type: str,
    expected_module: str,
):
    event = AutomationEvent(
        business_id="business-001",
        event_type=event_type,
        payload={},
    )

    assert AutomationRouter.module_for(event) == expected_module


def test_router_rejects_non_event():
    with pytest.raises(TypeError, match="AutomationEvent"):
        AutomationRouter.module_for(object())


def test_router_mapping_is_explicit():
    assert set(AutomationRouter.__dict__) >= {"module_for"}
