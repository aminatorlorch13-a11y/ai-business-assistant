import pytest

from app.ai.capability_response_parser import AICapabilityResponseParser
from app.assistant.capability import Capability


def valid_result() -> dict[str, object]:
    return {
        "response": "I can calculate that.",
        "capability_requests": [
            {
                "capability": "calculator",
                "operation": "calculate",
                "arguments": {
                    "expression": "15% of 2400",
                },
                "reason": "Calculate the requested percentage.",
                "reversible": True,
            }
        ],
    }


def test_parser_accepts_response_only() -> None:
    result = AICapabilityResponseParser().parse(
        {
            "response": "Hello.",
            "capability_requests": [],
        }
    )

    assert result.response == "Hello."
    assert result.capability_requests == ()


def test_parser_accepts_capability_request_only() -> None:
    result = AICapabilityResponseParser().parse(
        {
            "response": None,
            "capability_requests": valid_result()["capability_requests"],
        }
    )

    assert result.response is None
    assert len(result.capability_requests) == 1
    assert result.capability_requests[0].capability is Capability.CALCULATOR


def test_parser_accepts_multiple_capability_requests() -> None:
    result = AICapabilityResponseParser().parse(
        {
            "response": "I will handle both.",
            "capability_requests": [
                valid_result()["capability_requests"][0],
                {
                    "capability": "time",
                    "operation": "get_current_time",
                    "arguments": {},
                    "reason": "Retrieve the current time.",
                    "reversible": True,
                },
            ],
        }
    )

    assert len(result.capability_requests) == 2
    assert result.capability_requests[0].capability is Capability.CALCULATOR
    assert result.capability_requests[1].capability is Capability.TIME


def test_parser_normalizes_response() -> None:
    result = AICapabilityResponseParser().parse(
        {
            "response": "  Hello.  ",
            "capability_requests": [],
        }
    )

    assert result.response == "Hello."


def test_parser_allows_null_response() -> None:
    result = AICapabilityResponseParser().parse(
        {
            "response": None,
            "capability_requests": valid_result()["capability_requests"],
        }
    )

    assert result.response is None


def test_parser_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="mapping"):
        AICapabilityResponseParser().parse([])  # type: ignore[arg-type]


def test_parser_rejects_missing_top_level_field() -> None:
    response = valid_result()
    response.pop("response")

    with pytest.raises(ValueError, match="missing required fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_unknown_top_level_field() -> None:
    response = valid_result()
    response["business_id"] = "business-001"

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_non_list_capability_requests() -> None:
    response = valid_result()
    response["capability_requests"] = {}

    with pytest.raises(ValueError, match="must be a list"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_missing_request_field() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request.pop("operation")

    with pytest.raises(ValueError, match="missing required fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_unknown_request_field() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["handler"] = "os.system"

    with pytest.raises(ValueError, match="unknown fields"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_unknown_capability() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["capability"] = "shell"

    with pytest.raises(ValueError, match="Unknown capability"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_non_string_capability() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["capability"] = {"value": "calculator"}

    with pytest.raises(ValueError, match="capability.*string"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_empty_operation() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["operation"] = "   "

    with pytest.raises(ValueError, match="operation"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_non_mapping_arguments() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["arguments"] = "2 + 2"

    with pytest.raises(ValueError, match="arguments.*mapping"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_empty_reason() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["reason"] = " "

    with pytest.raises(ValueError, match="reason"):
        AICapabilityResponseParser().parse(response)


def test_parser_rejects_non_boolean_reversible() -> None:
    response = valid_result()
    request = response["capability_requests"][0]  # type: ignore[index]
    request["reversible"] = "true"

    with pytest.raises(ValueError, match="reversible"):
        AICapabilityResponseParser().parse(response)
