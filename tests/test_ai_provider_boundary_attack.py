import json

import pytest

from app.ai.errors import AIProviderError
from app.ai.groq_config import GroqConfig
from app.ai.groq_provider import GroqHTTPProvider
from app.ai.openai_config import OpenAIConfig
from app.ai.openai_provider import OpenAIHTTPProvider
from app.assistant.message import AssistantMessage


def message() -> AssistantMessage:
    return AssistantMessage(
        business_id="business-1",
        content="Hello",
    )


def test_groq_provider_rejects_invalid_config_type():
    with pytest.raises(TypeError):
        GroqHTTPProvider(object())


def test_openai_provider_rejects_invalid_config_type():
    with pytest.raises(TypeError):
        OpenAIHTTPProvider(object())


def test_groq_extractor_rejects_non_mapping():
    with pytest.raises(AIProviderError):
        GroqHTTPProvider._extract_structured_output([])


@pytest.mark.parametrize(
    "response_data",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
    ],
)
def test_groq_extractor_rejects_malformed_responses(response_data):
    with pytest.raises(AIProviderError):
        GroqHTTPProvider._extract_structured_output(response_data)


@pytest.mark.parametrize(
    "response_data",
    [
        {},
        {"output": None},
        {"output": []},
        {"output": [{}]},
        {"output": [{"type": "message", "content": []}]},
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": ""},
                    ],
                }
            ]
        },
    ],
)
def test_openai_extractor_rejects_malformed_responses(response_data):
    with pytest.raises(AIProviderError):
        OpenAIHTTPProvider._extract_structured_output(response_data)


def test_groq_extractor_rejects_non_json_content():
    response = {
        "choices": [
            {
                "message": {
                    "content": "not-json",
                }
            }
        ]
    }

    with pytest.raises(AIProviderError):
        GroqHTTPProvider._extract_structured_output(response)


def test_openai_extractor_rejects_non_json_structured_content():
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "not-json",
                    }
                ],
            }
        ]
    }

    with pytest.raises(AIProviderError):
        OpenAIHTTPProvider._extract_structured_output(response)


def test_groq_extractor_accepts_mapping_after_json_decode():
    structured = {
        "intent_type": "general_question",
        "instruction": "Hello",
        "action_type": "none",
        "target": "assistant",
        "action_instruction": "Hello",
        "business_id": "business-1",
    }

    response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(structured),
                }
            }
        ]
    }

    assert GroqHTTPProvider._extract_structured_output(response) == structured


def test_openai_extractor_accepts_mapping_after_json_decode():
    structured = {
        "intent_type": "general_question",
        "instruction": "Hello",
        "action_type": "none",
        "target": "assistant",
        "action_instruction": "Hello",
        "business_id": "business-1",
    }

    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(structured),
                    }
                ],
            }
        ]
    }

    assert OpenAIHTTPProvider._extract_structured_output(response) == structured


@pytest.mark.parametrize(
    "config",
    [
        GroqConfig(
            api_key="gsk_test",
            timeout_seconds=1,
        ),
        OpenAIConfig(
            api_key="sk_test",
            timeout_seconds=1,
        ),
    ],
)
def test_provider_config_objects_are_immutable(config):
    with pytest.raises(AttributeError):
        config.api_key = "attacker"


def test_message_business_id_is_application_context():
    msg = message()

    assert msg.business_id == "business-1"


def test_groq_http_error_does_not_expose_provider_body(monkeypatch):
    from urllib.error import HTTPError

    secret_body = b'{"error":"SECRET_PROVIDER_INTERNAL_DATA"}'

    def fail(*args, **kwargs):
        raise HTTPError(
            url="https://example.invalid",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=__import__("io").BytesIO(secret_body),
        )

    monkeypatch.setattr("app.ai.groq_provider.urlopen", fail)

    provider = GroqHTTPProvider(
        GroqConfig(
            api_key="gsk_test",
            timeout_seconds=1,
        )
    )

    with pytest.raises(AIProviderError) as exc_info:
        provider.generate(message())

    error_text = str(exc_info.value)

    assert "500" in error_text
    assert "SECRET_PROVIDER_INTERNAL_DATA" not in error_text


def test_openai_http_error_does_not_expose_provider_body(monkeypatch):
    from urllib.error import HTTPError

    secret_body = b'{"error":"SECRET_PROVIDER_INTERNAL_DATA"}'

    def fail(*args, **kwargs):
        raise HTTPError(
            url="https://example.invalid",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=__import__("io").BytesIO(secret_body),
        )

    monkeypatch.setattr("app.ai.openai_provider.urlopen", fail)

    provider = OpenAIHTTPProvider(
        OpenAIConfig(
            api_key="sk_test",
            timeout_seconds=1,
        )
    )

    with pytest.raises(AIProviderError) as exc_info:
        provider.generate(message())

    error_text = str(exc_info.value)

    assert "500" in error_text
    assert "SECRET_PROVIDER_INTERNAL_DATA" not in error_text


class FailingRawProvider:
    def generate(self, message):
        raise RuntimeError("SECRET_PROVIDER_EXCEPTION")


def test_interpreting_provider_does_not_expose_raw_provider_exception():
    from app.ai.interpreting_provider import InterpretingAIProvider

    provider = InterpretingAIProvider(FailingRawProvider())

    with pytest.raises(AIProviderError) as exc_info:
        provider.interpret(message())

    assert str(exc_info.value) == "AI provider failed."
    assert "SECRET_PROVIDER_EXCEPTION" not in str(exc_info.value)
