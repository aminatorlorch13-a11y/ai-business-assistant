import pytest

from app.assistant.capability import (
    Capability,
    CapabilityRequest,
)


def make_request(
    capability: Capability = Capability.CONVERSATION,
) -> CapabilityRequest:
    return CapabilityRequest(
        capability=capability,
        business_id="business-001",
        reason="Handle the owner's request.",
    )


def test_capability_values_are_stable():
    assert Capability.CONVERSATION.value == "conversation"
    assert Capability.TIME.value == "time"
    assert Capability.MEMORY.value == "memory"
    assert Capability.RESEARCH.value == "research"
    assert Capability.AUTOMATION.value == "automation"
    assert Capability.COMMUNICATION.value == "communication"
    assert Capability.VOICE.value == "voice"


def test_capability_request_accepts_valid_input():
    request = make_request()

    assert request.capability is Capability.CONVERSATION
    assert request.business_id == "business-001"
    assert request.reason == "Handle the owner's request."


def test_capability_request_is_immutable():
    request = make_request()

    with pytest.raises(AttributeError):
        request.reason = "Changed."


@pytest.mark.parametrize(
    "capability",
    [None, "conversation", 123],
)
def test_capability_request_rejects_invalid_capability(
    capability,
):
    with pytest.raises(TypeError, match="capability"):
        CapabilityRequest(
            capability=capability,
            business_id="business-001",
            reason="Handle request.",
        )


@pytest.mark.parametrize(
    "business_id",
    ["", "   ", None, 123],
)
def test_capability_request_rejects_invalid_business_id(
    business_id,
):
    with pytest.raises((TypeError, ValueError), match="business_id"):
        CapabilityRequest(
            capability=Capability.CONVERSATION,
            business_id=business_id,
            reason="Handle request.",
        )


@pytest.mark.parametrize(
    "reason",
    ["", "   ", None, 123],
)
def test_capability_request_rejects_invalid_reason(reason):
    with pytest.raises((TypeError, ValueError), match="reason"):
        CapabilityRequest(
            capability=Capability.CONVERSATION,
            business_id="business-001",
            reason=reason,
        )
