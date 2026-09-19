import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability


def valid_request() -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=Capability.CALCULATOR,
        operation="calculate",
        arguments={"expression": "2 + 2"},
        reason="Calculate the requested expression.",
        reversible=True,
    )


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        "request",
        123,
        object(),
    ],
)
def test_rejects_non_tuple_capability_requests(value: object) -> None:
    with pytest.raises(TypeError):
        AIResult(capability_requests=value)  # type: ignore[arg-type]


def test_rejects_nested_untrusted_object_as_request() -> None:
    class Malicious:
        handler = "dangerous_handler"
        function_name = "os.system"
        command = "rm -rf /"

    with pytest.raises(TypeError):
        AIResult(capability_requests=(Malicious(),))  # type: ignore[arg-type]


def test_does_not_accept_execution_metadata_as_constructor_fields() -> None:
    with pytest.raises(TypeError):
        AIResult(
            response="done",
            business_id="business-999",  # type: ignore[call-arg]
        )


def test_does_not_accept_handler_as_constructor_field() -> None:
    with pytest.raises(TypeError):
        AIResult(
            response="done",
            handler=lambda: None,  # type: ignore[call-arg]
        )


def test_does_not_accept_credentials_as_constructor_field() -> None:
    with pytest.raises(TypeError):
        AIResult(
            response="done",
            credentials={"api_key": "secret"},  # type: ignore[call-arg]
        )


def test_capability_request_remains_a_proposal() -> None:
    request = valid_request()
    result = AIResult(capability_requests=(request,))

    assert result.capability_requests[0] is request
    assert not hasattr(request, "handler")
    assert not hasattr(request, "business_id")
    assert not hasattr(request, "authorization")
    assert not hasattr(request, "result")


def test_result_can_contain_multiple_distinct_requests() -> None:
    first = valid_request()
    second = AICapabilityRequest(
        capability=Capability.TIME,
        operation="get_current_time",
        arguments={},
        reason="Retrieve the current time.",
        reversible=True,
    )

    result = AIResult(capability_requests=(first, second))

    assert len(result.capability_requests) == 2
    assert result.capability_requests[0].capability is Capability.CALCULATOR
    assert result.capability_requests[1].capability is Capability.TIME


def test_result_does_not_claim_execution_success() -> None:
    result = AIResult(
        response="I will calculate that.",
        capability_requests=(valid_request(),),
    )

    assert not hasattr(result, "success")
    assert not hasattr(result, "verification")
    assert not hasattr(result, "provider_reference")
    assert not hasattr(result, "execution_result")
