from dataclasses import FrozenInstanceError

import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.ai_result import AIResult
from app.assistant.capability import Capability


def make_request(
    *,
    capability: Capability = Capability.CALCULATOR,
    operation: str = "calculate",
    arguments: dict[str, object] | None = None,
    reason: str = "Calculate the requested value.",
    reversible: bool = True,
) -> AICapabilityRequest:
    return AICapabilityRequest(
        capability=capability,
        operation=operation,
        arguments=arguments or {"expression": "15% of 2400"},
        reason=reason,
        reversible=reversible,
    )


def test_accepts_response_only() -> None:
    result = AIResult(response="Hello.")

    assert result.response == "Hello."
    assert result.capability_requests == ()


def test_accepts_capability_request_only() -> None:
    request = make_request()

    result = AIResult(capability_requests=(request,))

    assert result.response is None
    assert result.capability_requests == (request,)


def test_accepts_response_and_multiple_capability_requests() -> None:
    first = make_request()
    second = make_request(
        capability=Capability.TIME,
        operation="get_current_time",
        arguments={},
        reason="Retrieve the current time.",
    )

    result = AIResult(
        response="I can handle those requests.",
        capability_requests=(first, second),
    )

    assert result.response == "I can handle those requests."
    assert result.capability_requests == (first, second)


def test_normalizes_response() -> None:
    result = AIResult(response="  Hello.  ")

    assert result.response == "Hello."


def test_rejects_empty_response() -> None:
    with pytest.raises(ValueError):
        AIResult(response="   ")


def test_rejects_non_string_response() -> None:
    with pytest.raises(TypeError):
        AIResult(response=123)  # type: ignore[arg-type]


def test_rejects_empty_result() -> None:
    with pytest.raises(ValueError):
        AIResult()


def test_requires_tuple_for_capability_requests() -> None:
    with pytest.raises(TypeError):
        AIResult(capability_requests=[make_request()])  # type: ignore[arg-type]


def test_rejects_non_capability_request_items() -> None:
    with pytest.raises(TypeError):
        AIResult(capability_requests=("not-a-request",))  # type: ignore[arg-type]


def test_result_is_immutable() -> None:
    result = AIResult(response="Hello.")

    with pytest.raises(FrozenInstanceError):
        result.response = "Changed."  # type: ignore[misc]
