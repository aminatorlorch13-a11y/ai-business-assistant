import json

from app.ai.capability_response_parser import AICapabilityResponseParser
from app.ai.groq_provider import GroqHTTPProvider
from app.ai.openai_provider import OpenAIHTTPProvider


def test_groq_system_instructions_define_new_ai_result_contract():
    instructions = GroqHTTPProvider.SYSTEM_INSTRUCTIONS

    assert '"response"' in instructions
    assert '"capability_requests"' in instructions
    assert '"capability"' in instructions
    assert '"operation"' in instructions
    assert '"arguments"' in instructions
    assert '"reason"' in instructions
    assert '"reversible"' in instructions

    assert 'Never return "business_id".' in instructions
    assert "handler" in instructions
    assert "function" in instructions
    assert "credentials" in instructions
    assert "Python" in instructions
    assert "SQL" in instructions
    assert "shell" in instructions


def test_openai_response_schema_is_exact_new_contract_shape():
    schema = OpenAIHTTPProvider.RESPONSE_SCHEMA

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "response",
        "capability_requests",
    }
    assert set(schema["required"]) == {
        "response",
        "capability_requests",
    }

    request_schema = schema["properties"]["capability_requests"]["items"]

    assert request_schema["type"] == "object"
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {
        "capability",
        "operation",
        "arguments",
        "reason",
        "reversible",
    }
    assert set(request_schema["required"]) == {
        "capability",
        "operation",
        "arguments",
        "reason",
        "reversible",
    }


def test_openai_schema_does_not_expose_business_identity_or_execution_control():
    schema_text = json.dumps(OpenAIHTTPProvider.RESPONSE_SCHEMA)

    forbidden = {
        "business_id",
        "handler",
        "function",
        "tool",
        "credentials",
        "api_key",
        "execution",
        "execution_result",
    }

    for field in forbidden:
        assert field not in schema_text


def test_openai_system_instructions_define_application_owned_identity():
    instructions = OpenAIHTTPProvider.SYSTEM_INSTRUCTIONS

    assert 'Never return "business_id".' in instructions

    normalized = " ".join(instructions.split()).lower()
    assert "business identity is controlled by the application" in normalized



def test_new_provider_response_flows_into_new_parser():
    raw_response = {
        "response": "I can check that for you.",
        "capability_requests": [
            {
                "capability": "calculator",
                "operation": "calculate",
                "arguments": {
                    "expression": "25 * 4",
                },
                "reason": "The user requested a calculation.",
                "reversible": True,
            }
        ],
    }

    result = AICapabilityResponseParser().parse(raw_response)

    assert result.response == "I can check that for you."
    assert len(result.capability_requests) == 1

    request = result.capability_requests[0]

    assert request.capability.value == "calculator"
    assert request.operation == "calculate"
    assert request.arguments["expression"] == "25 * 4"
    assert request.reason == "The user requested a calculation."
    assert request.reversible is True


def test_new_provider_response_does_not_become_legacy_interpretation():
    raw_response = {
        "response": None,
        "capability_requests": [
            {
                "capability": "time",
                "operation": "current_time",
                "arguments": {
                    "timezone": "Africa/Johannesburg",
                },
                "reason": "The user requested the current time.",
                "reversible": True,
            }
        ],
    }

    result = AICapabilityResponseParser().parse(raw_response)

    assert result.response is None
    assert len(result.capability_requests) == 1
    assert not hasattr(result, "business_id")
    assert not hasattr(result, "action")
    assert not hasattr(result, "intent")
