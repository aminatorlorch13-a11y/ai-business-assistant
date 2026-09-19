import pytest

from app.assistant.ai_capability_request import AICapabilityRequest
from app.assistant.capability import Capability


def valid_values():
    return {
        "capability": Capability.CALCULATOR,
        "operation": "calculate",
        "arguments": {"expression": "2 + 2"},
        "reason": "Calculate the requested expression.",
        "reversible": True,
    }


@pytest.mark.parametrize(
    "malicious_field",
    [
        "python",
        "python_code",
        "code",
        "shell",
        "shell_command",
        "sql",
        "sql_query",
        "query",
        "handler",
        "handler_path",
        "function",
        "function_name",
        "callable",
    ],
)
def test_untrusted_execution_fields_are_not_part_of_contract(malicious_field):
    values = valid_values()
    values[malicious_field] = "malicious payload"

    with pytest.raises(TypeError):
        AICapabilityRequest(**values)


@pytest.mark.parametrize(
    "operation",
    [
        "__import__('os').system('id')",
        "os.system",
        "subprocess.run",
        "database.execute",
        "shell.execute",
    ],
)
def test_operation_is_only_data_at_this_boundary(operation):
    request = AICapabilityRequest(
        **{
            **valid_values(),
            "operation": operation,
        }
    )

    assert request.operation == operation


def test_ai_request_cannot_control_business_identity():
    values = valid_values()
    values["business_id"] = "attacker-business"

    with pytest.raises(TypeError):
        AICapabilityRequest(**values)


def test_ai_request_cannot_grant_authorization():
    values = valid_values()
    values["authorized"] = True

    with pytest.raises(TypeError):
        AICapabilityRequest(**values)


def test_ai_request_cannot_select_arbitrary_capability_by_string():
    values = valid_values()
    values["capability"] = "communication"

    with pytest.raises(TypeError):
        AICapabilityRequest(**values)


def test_ai_request_cannot_be_used_to_mutate_original_arguments():
    arguments = {"expression": "2 + 2"}

    request = AICapabilityRequest(
        **{
            **valid_values(),
            "arguments": arguments,
        }
    )

    arguments.clear()

    assert request.arguments == {"expression": "2 + 2"}


def test_nested_argument_values_are_not_executed_by_contract():
    payload = {
        "expression": "2 + 2",
        "nested": {
            "python_code": "raise RuntimeError('should never execute')",
            "shell_command": "echo attacker",
        },
    }

    request = AICapabilityRequest(
        **{
            **valid_values(),
            "arguments": payload,
        }
    )

    assert request.arguments["nested"]["python_code"].startswith("raise")
    assert request.arguments["nested"]["shell_command"] == "echo attacker"
