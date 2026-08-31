from unittest.mock import Mock

from app.assistant.message import AssistantMessage
from app.assistant.processor import AssistantProcessor
from app.assistant.response import AssistantResponse


def test_processor_delegates_to_ai_provider():
    provider = Mock()

    expected_response = AssistantResponse(
        business_id="business-001",
        assistant_name="OwnerChosenName",
        message="I will check that for you.",
    )

    provider.respond.return_value = expected_response

    processor = AssistantProcessor(provider)

    message = AssistantMessage(
        business_id="business-001",
        content="Please check tomorrow's appointments.",
    )

    result = processor.process(message)

    assert result == expected_response
    provider.respond.assert_called_once_with(message)
