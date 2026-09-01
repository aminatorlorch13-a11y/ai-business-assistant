import pytest

from app.assistant.core import AssistantCore
from app.assistant.request import AssistantRequest
from app.models.business import Business


def make_business() -> Business:
    return Business(
        business_id="business-001",
        name="Business One",
        owner_name="Owner One",
        assistant_name="Business Assistant",
        assistant_voice="female",
    )


def test_assistant_uses_configured_business_identity():
    business = make_business()
    assistant = AssistantCore(business)

    request = AssistantRequest(
        business_id="business-001",
        message="Good morning.",
    )

    response = assistant.handle(request)

    assert response.business_id == "business-001"
    assert response.assistant_name == "Business Assistant"
    assert response.message == "Good morning."
    assert response.should_speak is True


def test_assistant_rejects_request_for_another_business():
    business = make_business()
    assistant = AssistantCore(business)

    request = AssistantRequest(
        business_id="business-999",
        message="Hello.",
    )

    with pytest.raises(ValueError):
        assistant.handle(request)


def test_core_rejects_invalid_business_dependency():
    with pytest.raises(TypeError, match="business"):
        AssistantCore(object())


def test_core_rejects_invalid_request_type():
    assistant = AssistantCore(make_business())

    with pytest.raises(TypeError, match="request"):
        assistant.handle("Good morning.")


def test_core_does_not_process_wrong_business_request():
    assistant = AssistantCore(make_business())

    request = AssistantRequest(
        business_id="business-999",
        message="Hello.",
    )

    with pytest.raises(ValueError, match="business"):
        assistant.handle(request)
