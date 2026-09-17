import pytest

from app.assistant.message import AssistantMessage


def test_message_accepts_valid_data():
    message = AssistantMessage(
        business_id="business-001",
        content="Please check tomorrow's appointments.",
    )

    assert message.business_id == "business-001"
    assert message.content == "Please check tomorrow's appointments."


def test_message_rejects_empty_business_id():
    with pytest.raises(ValueError):
        AssistantMessage(
            business_id="",
            content="Hello",
        )


def test_message_rejects_empty_content():
    with pytest.raises(ValueError):
        AssistantMessage(
            business_id="business-001",
            content="",
        )
