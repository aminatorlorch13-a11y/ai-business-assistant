import pytest

from app.ai.capability_response_parser import AICapabilityResponseParser
from app.assistant.capability import Capability


def valid_result() -> dict[str, object]:
    return {
        "response": "I can help with that.",
        "capability_requests": [
            {
                "capability": "calculator",
                "operation": "calculate",
                "arguments": {"expression": "2 + 2"},
                "reason": "Calculate the requested expression.",
                "reversible": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "malicious_field",
    [
        "business_id",
        "handler",
        "function",
        "callable",
        "tool",
        "tool_name",
        "execution",
        "execution_result",
        "provider_reference",
        "credentials",
        "api_key",
        "shell",
        "python",
        "sql",
    ],
)
def test_parser_rejects_control_plane_fields(malicious_field: str) -> None:
    response = valid_result()
    response["capability_requests"][0][malicious_field] = "malicious"

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_business_identity_at_top_level() -> None:
    response = valid_result()
    response["business_id"] = "attacker-business"

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_nested_request_business_identity() -> None:
    response = valid_result()
    response["capability_requests"][0]["business_id"] = "attacker-business"

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


@pytest.mark.parametrize(
    "capability_value",
    [
        "__import__('os').system('id')",
        "shell",
        "filesystem",
        "database",
        "python",
        "subprocess",
    ],
)
def test_parser_rejects_capability_escape_attempts(
    capability_value: str,
) -> None:
    response = valid_result()
    response["capability_requests"][0]["capability"] = capability_value

    with pytest.raises(ValueError, match="Unknown capability"):
        AICapabilityResponseParser().parse(response)


@pytest.mark.parametrize(
    "operation",
    [
        "__import__('os').system('id')",
        "shell_exec",
        "python_exec",
        "subprocess",
        "eval",
        "exec",
        "../../etc/passwd",
    ],
)
def test_parser_does_not_turn_operation_into_execution(
    operation: str,
) -> None:
    response = valid_result()
    response["capability_requests"][0]["operation"] = operation

    # The parser validates the structural contract only.
    # Operation allowlisting belongs to the capability router.
    result = AICapabilityResponseParser().parse(response)

    assert result.capability_requests[0].operation == operation


def test_parser_allows_operation_arguments_without_granting_execution() -> None:
    response = valid_result()
    response["capability_requests"][0]["arguments"] = {
        "expression": "2 + 2",
        "metadata": {
            "requested_by": "customer",
            "arbitrary_value": ["a", "b", {"nested": True}],
        },
    }

    result = AICapabilityResponseParser().parse(response)

    assert result.capability_requests[0].arguments["expression"] == "2 + 2"


def test_parser_freezes_top_level_arguments_container() -> None:
    response = valid_result()

    result = AICapabilityResponseParser().parse(response)
    arguments = result.capability_requests[0].arguments

    with pytest.raises(TypeError):
        arguments["new_value"] = "blocked"  # type: ignore[index]


def test_parser_does_not_execute_malicious_argument_values() -> None:
    response = valid_result()
    response["capability_requests"][0]["arguments"] = {
        "expression": "__import__('os').system('id')"
    }

    result = AICapabilityResponseParser().parse(response)

    assert (
        result.capability_requests[0].arguments["expression"]
        == "__import__('os').system('id')"
    )


def test_parser_rejects_fake_capability_result() -> None:
    response = valid_result()
    response["capability_requests"][0]["success"] = True

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_fake_handler_reference() -> None:
    response = valid_result()
    response["capability_requests"][0]["handler"] = {
        "module": "os",
        "function": "system",
    }

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


@pytest.mark.parametrize(
    "reversible",
    [1, 0, "true", "false", None, [], {}],
)
def test_parser_rejects_non_boolean_reversible_values(
    reversible: object,
) -> None:
    response = valid_result()
    response["capability_requests"][0]["reversible"] = reversible

    with pytest.raises(ValueError, match="reversible must be a boolean"):
        AICapabilityResponseParser().parse(response)


@pytest.mark.parametrize(
    "response_value",
    [123, {}, [], True, False],
)
def test_parser_rejects_non_string_response_values(
    response_value: object,
) -> None:
    response = valid_result()
    response["response"] = response_value

    with pytest.raises(
        ValueError,
        match="response.*string or null",
    ):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_tuple_capability_requests() -> None:
    response = valid_result()
    response["capability_requests"] = tuple(
        response["capability_requests"]  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="must be a list"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_request_scalar_values() -> None:
    response = valid_result()
    response["capability_requests"] = [
        "calculator.calculate",
    ]

    with pytest.raises(
        ValueError,
        match="Invalid capability request",
    ):
        AICapabilityResponseParser().parse(response)


def test_parser_preserves_capability_enum() -> None:
    result = AICapabilityResponseParser().parse(valid_result())

    request = result.capability_requests[0]

    assert request.capability is Capability.CALCULATOR
    assert isinstance(request.capability, Capability)


def test_parser_produces_immutable_ai_result() -> None:
    result = AICapabilityResponseParser().parse(valid_result())

    with pytest.raises(AttributeError):
        result.response = "tampered"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        result.capability_requests = ()  # type: ignore[misc]


def test_parser_rejects_mixed_control_fields_even_with_valid_request() -> None:
    response = valid_result()
    response["capability_requests"][0].update(
        {
            "handler": "calculator_handler",
            "provider_reference": "provider-123",
            "credentials": {"token": "secret"},
            "execution_result": {"success": True},
        }
    )

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)
