import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.capability import Capability


def make_request(**overrides) -> AICapabilityRequest:
    values = {
        "capability": Capability.CALCULATOR,
        "operation": "calculate",
        "arguments": {"expression": "15% of 2400"},
        "reason": "Calculate the percentage requested by the user.",
        "reversible": True,
    }
    values.update(overrides)
    return AICapabilityRequest(**values)


def test_request_accepts_valid_input():
    request = make_request()

    assert request.capability is Capability.CALCULATOR
    assert request.operation == "calculate"
    assert request.arguments["expression"] == "15% of 2400"
    assert request.reason == "Calculate the percentage requested by the user."
    assert request.reversible is True


def test_request_normalizes_strings():
    request = make_request(
        operation="  calculate  ",
        reason="  Calculate the requested value.  ",
    )

    assert request.operation == "calculate"
    assert request.reason == "Calculate the requested value."


def test_request_freezes_top_level_arguments():
    arguments = {"expression": "2 + 2"}
    request = make_request(arguments=arguments)

    arguments["expression"] = "9 * 9"
    arguments["unexpected"] = "value"

    assert request.arguments["expression"] == "2 + 2"
    assert "unexpected" not in request.arguments

    with pytest.raises(TypeError):
        request.arguments["expression"] = "5 + 5"


def test_request_is_immutable():
    request = make_request()

    with pytest.raises(AttributeError):
        request.operation = "delete"


@pytest.mark.parametrize(
    "capability",
    [None, "calculator", 123],
)
def test_request_rejects_invalid_capability(capability):
    with pytest.raises(TypeError, match="capability"):
        make_request(capability=capability)


@pytest.mark.parametrize(
    "operation",
    ["", "   ", None, 123],
)
def test_request_rejects_invalid_operation(operation):
    with pytest.raises((TypeError, ValueError), match="operation"):
        make_request(operation=operation)


@pytest.mark.parametrize(
    "arguments",
    [None, [], "arguments", 123],
)
def test_request_rejects_invalid_arguments(arguments):
    with pytest.raises(TypeError, match="arguments"):
        make_request(arguments=arguments)


@pytest.mark.parametrize(
    "reason",
    ["", "   ", None, 123],
)
def test_request_rejects_invalid_reason(reason):
    with pytest.raises((TypeError, ValueError), match="reason"):
        make_request(reason=reason)


@pytest.mark.parametrize(
    "reversible",
    [None, "true", 1, 0, []],
)
def test_request_rejects_invalid_reversible(reversible):
    with pytest.raises(TypeError, match="reversible"):
        make_request(reversible=reversible)


def test_request_does_not_accept_business_identity():
    with pytest.raises(TypeError, match="business_id"):
        make_request(business_id="business-001")


def test_request_does_not_accept_execution_metadata():
    with pytest.raises(TypeError, match="channel"):
        make_request(channel="web")


def test_request_does_not_accept_executable_handler_fields():
    with pytest.raises(TypeError, match="handler"):
        make_request(handler="some.python.function")

    with pytest.raises(TypeError, match="function_name"):
        make_request(function_name="execute_shell")


def test_request_arguments_are_data_not_an_execution_hook():
    request = make_request(
        arguments={
            "expression": "2 + 2",
            "python_code": "import os; os.system('rm -rf /')",
            "shell_command": "rm -rf /",
        }
    )

    assert request.arguments["expression"] == "2 + 2"
    assert request.arguments["python_code"].startswith("import os")
    assert request.arguments["shell_command"] == "rm -rf /"
