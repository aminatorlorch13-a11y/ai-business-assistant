import pytest

from app.assistant.capability import Capability
from app.assistant.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)


def test_request_normalizes_and_freezes_arguments():
    request = CapabilityExecutionRequest(
        capability=Capability.TIME,
        operation="  calculate  ",
        business_id="  biz-1  ",
        arguments={"expression": "2 + 2"},
        reason="  User requested calculation.  ",
        channel=" web ",
        integration=" local ",
    )

    assert request.operation == "calculate"
    assert request.business_id == "biz-1"
    assert request.reason == "User requested calculation."
    assert request.channel == "web"
    assert request.integration == "local"
    assert request.arguments["expression"] == "2 + 2"

    with pytest.raises(TypeError):
        request.arguments["expression"] = "5 + 5"


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"capability": "calculator"}, TypeError),
        ({"operation": ""}, ValueError),
        ({"business_id": ""}, ValueError),
        ({"arguments": []}, TypeError),
        ({"reason": ""}, ValueError),
        ({"channel": 123}, TypeError),
        ({"integration": 123}, TypeError),
    ],
)
def test_request_rejects_invalid_fields(kwargs, error):
    values = {
        "capability": Capability.TIME,
        "operation": "calculate",
        "business_id": "biz-1",
        "arguments": {},
        "reason": "calculate something",
    }
    values.update(kwargs)

    with pytest.raises(error):
        CapabilityExecutionRequest(**values)


def test_result_accepts_verified_success():
    result = CapabilityExecutionResult(
        success=True,
        capability=Capability.TIME,
        operation="calculate",
        business_id="biz-1",
        data={"value": 4},
        verification="verified",
    )

    assert result.success is True
    assert result.capability is Capability.TIME
    assert result.operation == "calculate"
    assert result.business_id == "biz-1"
    assert result.data == {"value": 4}
    assert result.verification == "verified"


def test_result_accepts_failure_with_error():
    result = CapabilityExecutionResult(
        success=False,
        capability=Capability.TIME,
        operation="create_event",
        business_id="biz-1",
        error="Calendar integration is unavailable.",
    )

    assert result.success is False
    assert result.error == "Calendar integration is unavailable."


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"success": "yes"}, TypeError),
        ({"capability": "calendar"}, TypeError),
        ({"operation": ""}, ValueError),
        ({"business_id": ""}, ValueError),
        ({"provider_reference": 123}, TypeError),
        ({"verification": 123}, TypeError),
        ({"error": 123}, TypeError),
    ],
)
def test_result_rejects_invalid_fields(kwargs, error):
    values = {
        "success": True,
        "capability": Capability.TIME,
        "operation": "calculate",
        "business_id": "biz-1",
    }
    values.update(kwargs)

    with pytest.raises(error):
        CapabilityExecutionResult(**values)


def test_successful_result_rejects_error():
    with pytest.raises(ValueError, match="successful results cannot contain an error"):
        CapabilityExecutionResult(
            success=True,
            capability=Capability.TIME,
            operation="get_time",
            business_id="biz-1",
            error="Unexpected failure.",
        )


def test_failed_result_requires_error():
    with pytest.raises(ValueError, match="failed results must contain an error"):
        CapabilityExecutionResult(
            success=False,
            capability=Capability.TIME,
            operation="get_time",
            business_id="biz-1",
        )
