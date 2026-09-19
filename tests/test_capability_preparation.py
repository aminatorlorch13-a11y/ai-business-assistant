import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.capability import Capability
from app.assistant.capability_preparation import CapabilityExecutionPreparer
from app.assistant.execution import CapabilityExecutionRequest


def make_request() -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.CALENDAR,
        operation="create_event",
        arguments={
            "title": "Team meeting",
            "attendee": "owner@example.com",
        },
        reason="Create the requested calendar event.",
        reversible=True,
    )


def test_prepare_adds_trusted_execution_context():
    request = make_request()

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id="business-001",
        channel="web",
        integration="google_calendar",
    )

    assert isinstance(result, CapabilityExecutionRequest)
    assert result.capability is Capability.CALENDAR
    assert result.operation == "create_event"
    assert result.business_id == "business-001"
    assert result.arguments["title"] == "Team meeting"
    assert result.reason == "Create the requested calendar event."
    assert result.channel == "web"
    assert result.integration == "google_calendar"


def test_prepare_does_not_copy_ai_reversible_flag():
    request = make_request()

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id="business-001",
    )

    assert not hasattr(result, "reversible")


def test_prepare_uses_application_business_identity():
    request = make_request()

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id="trusted-business",
    )

    assert result.business_id == "trusted-business"


@pytest.mark.parametrize(
    "business_id",
    ["", "   ", None, 123],
)
def test_prepare_rejects_invalid_business_id(business_id):
    with pytest.raises((TypeError, ValueError)):
        CapabilityExecutionPreparer().prepare(
            make_request(),
            business_id=business_id,
        )


@pytest.mark.parametrize(
    "channel",
    ["", "   ", 123],
)
def test_prepare_rejects_invalid_channel(channel):
    with pytest.raises((TypeError, ValueError)):
        CapabilityExecutionPreparer().prepare(
            make_request(),
            business_id="business-001",
            channel=channel,
        )


@pytest.mark.parametrize(
    "integration",
    ["", "   ", 123],
)
def test_prepare_rejects_invalid_integration(integration):
    with pytest.raises((TypeError, ValueError)):
        CapabilityExecutionPreparer().prepare(
            make_request(),
            business_id="business-001",
            integration=integration,
        )


def test_prepare_rejects_non_ai_request():
    with pytest.raises(TypeError, match="AICapabilityRequest"):
        CapabilityExecutionPreparer().prepare(
            object(),
            business_id="business-001",
        )


def test_prepare_preserves_inert_ai_arguments():
    request = AICapabilityRequest(
        capability=Capability.CALCULATOR,
        operation="calculate",
        arguments={
            "expression": "__import__('os').system('whoami')",
            "handler": "malicious_handler",
        },
        reason="Calculate the requested expression.",
        reversible=False,
    )

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id="business-001",
    )

    assert result.arguments["expression"] == "__import__('os').system('whoami')"
    assert result.arguments["handler"] == "malicious_handler"


def test_prepare_freezes_execution_arguments():
    request = make_request()

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id="business-001",
    )

    with pytest.raises(TypeError):
        result.arguments["title"] = "Tampered"


def test_prepare_copies_business_context_strings():
    request = make_request()

    business_id = "business-001"
    channel = "web"
    integration = "google_calendar"

    result = CapabilityExecutionPreparer().prepare(
        request,
        business_id=business_id,
        channel=channel,
        integration=integration,
    )

    assert result.business_id == "business-001"
    assert result.channel == "web"
    assert result.integration == "google_calendar"
