from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from app.assistant.message import AssistantMessage
from app.cli.chat import (
    _extract_confirmation_id,
    _handle_message,
)
from app.identity.models import AuthenticatedPrincipal, UserRole
from app.identity.tenant import TenantContext


CHAT_PATH = Path("app/cli/chat.py")
FACTORY_PATH = Path("app/cli/assistant_factory.py")


def make_tenant() -> TenantContext:
    principal = AuthenticatedPrincipal(
        user_id="user-cli-1",
        business_id="business-cli-1",
        role=UserRole.OWNER,
        session_id="session-cli-1",
    )
    return TenantContext(
        business_id="business-cli-1",
        principal=principal,
    )


class RecordingAssistant:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def handle(self, message, **kwargs):
        self.calls.append(
            {
                "message": message,
                "kwargs": kwargs,
            }
        )
        return self.responses.pop(0)


def response(message: str, assistant_name: str = "Assistant"):
    return SimpleNamespace(
        assistant_name=assistant_name,
        message=message,
    )


def test_extract_confirmation_id_requires_exact_marker():
    assert (
        _extract_confirmation_id(
            "Confirmation required. Confirmation ID: abc123"
        )
        == "abc123"
    )


def test_extract_confirmation_id_rejects_missing_marker():
    assert _extract_confirmation_id("Confirmation required.") is None


def test_extract_confirmation_id_rejects_non_string():
    assert _extract_confirmation_id(None) is None


def test_extract_confirmation_id_rejects_empty_id():
    assert (
        _extract_confirmation_id(
            "Confirmation ID: "
        )
        is None
    )


def test_normal_response_does_not_request_confirmation(monkeypatch, capsys):
    assistant = RecordingAssistant(
        [
            response("Everything is fine."),
        ]
    )
    tenant = make_tenant()

    def fail_input(_):
        raise AssertionError(
            "CLI must not ask for confirmation for a normal response."
        )

    monkeypatch.setattr("builtins.input", fail_input)

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        "hello",
    )

    output = capsys.readouterr().out

    assert "Everything is fine." in output
    assert len(assistant.calls) == 1
    assert assistant.calls[0]["kwargs"] == {
        "tenant": tenant,
        "channel": "cli",
    }


def test_confirmation_response_prompts_and_decline_does_not_execute(
    monkeypatch,
    capsys,
):
    assistant = RecordingAssistant(
        [
            response(
                "Confirmation required. Confirmation ID: confirm-123"
            ),
        ]
    )
    tenant = make_tenant()

    monkeypatch.setattr(
        "builtins.input",
        lambda _: "no",
    )

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        "delete my saved memory",
    )

    output = capsys.readouterr().out

    assert "Confirmation ID: confirm-123" in output
    assert "I won't proceed" in output
    assert len(assistant.calls) == 1
    assert "confirmation_id" not in assistant.calls[0]["kwargs"]


def test_confirmation_response_approval_executes_using_id(
    monkeypatch,
    capsys,
):
    assistant = RecordingAssistant(
        [
            response(
                "Confirmation required. Confirmation ID: confirm-456"
            ),
            response("Memory deleted."),
        ]
    )
    tenant = make_tenant()

    monkeypatch.setattr(
        "builtins.input",
        lambda _: "yes",
    )

    original_text = "delete my saved memory"

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        original_text,
    )

    output = capsys.readouterr().out

    assert "Memory deleted." in output
    assert len(assistant.calls) == 2

    first_call = assistant.calls[0]
    second_call = assistant.calls[1]

    assert isinstance(first_call["message"], AssistantMessage)
    assert first_call["message"].content == original_text
    assert first_call["kwargs"] == {
        "tenant": tenant,
        "channel": "cli",
    }

    assert second_call["message"].content == original_text
    assert second_call["kwargs"] == {
        "tenant": tenant,
        "channel": "cli",
        "confirmation_id": "confirm-456",
    }


def test_confirmation_approval_does_not_set_confirmed_flag(
    monkeypatch,
):
    assistant = RecordingAssistant(
        [
            response(
                "Confirmation required. Confirmation ID: confirm-789"
            ),
            response("Done."),
        ]
    )
    tenant = make_tenant()

    monkeypatch.setattr(
        "builtins.input",
        lambda _: "yes",
    )

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        "delete memory",
    )

    for call in assistant.calls:
        assert "confirmed" not in call["kwargs"]


def test_confirmation_response_with_malformed_id_does_not_prompt(
    monkeypatch,
    capsys,
):
    assistant = RecordingAssistant(
        [
            response(
                "Confirmation required. Confirmation ID: "
            ),
        ]
    )
    tenant = make_tenant()

    def fail_input(_):
        raise AssertionError(
            "Malformed confirmation must not reach interactive approval."
        )

    monkeypatch.setattr("builtins.input", fail_input)

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        "delete memory",
    )

    output = capsys.readouterr().out

    assert "Confirmation ID:" in output
    assert len(assistant.calls) == 1


def test_cli_preserves_authenticated_tenant_identity():
    assistant = RecordingAssistant(
        [
            response("Okay."),
        ]
    )
    tenant = make_tenant()

    _handle_message(
        assistant,
        tenant,
        "Assistant",
        "hello",
    )

    call = assistant.calls[0]

    assert call["kwargs"]["tenant"] is tenant
    assert call["kwargs"]["tenant"].business_id == "business-cli-1"
    assert (
        call["kwargs"]["tenant"].principal.business_id
        == "business-cli-1"
    )
    assert (
        call["message"].business_id
        == "business-cli-1"
    )


def test_cli_source_contains_no_legacy_execution_imports():
    source = CHAT_PATH.read_text()

    forbidden = (
        "app.assistant.action",
        "app.assistant.action_executor",
        "app.assistant.processor",
        "app.assistant.interpretation",
        "app.trust.action_policy",
        "app.trust.action_safety",
        "app.services.target_routed_operation",
        "app.services.appointment_operation",
        "app.services.business_operation",
        "app.services.assistant_conversation_operation",
    )

    for module in forbidden:
        assert module not in source


def test_cli_factory_source_contains_no_legacy_execution_imports():
    source = FACTORY_PATH.read_text()

    forbidden = (
        "app.assistant.action",
        "app.assistant.action_executor",
        "app.assistant.processor",
        "app.assistant.interpretation",
        "app.trust.action_policy",
        "app.trust.action_safety",
        "app.services.target_routed_operation",
        "app.services.appointment_operation",
        "app.services.business_operation",
        "app.services.assistant_conversation_operation",
    )

    for module in forbidden:
        assert module not in source


def test_cli_source_does_not_use_confirmed_true():
    tree = ast.parse(CHAT_PATH.read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        for keyword in node.keywords:
            if keyword.arg == "confirmed":
                assert not (
                    isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ), "CLI must never bypass durable confirmation."


def test_cli_source_does_not_construct_assistant_actions():
    tree = ast.parse(CHAT_PATH.read_text())

    forbidden_names = {
        "AssistantAction",
        "ActionExecutor",
        "ActionPolicy",
        "InterpretingAIProvider",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in forbidden_names


def test_confirmation_approval_does_not_reprocess_ai():
    assistant = RecordingAssistant(
        [
            response(
                "Confirmation required. Confirmation ID: confirm-no-reprocess"
            ),
            response("Executed."),
        ]
    )
    tenant = make_tenant()

    inputs = iter(["yes"])

    def fake_input(_):
        return next(inputs)

    import builtins

    original_input = builtins.input
    try:
        builtins.input = fake_input

        _handle_message(
            assistant,
            tenant,
            "Assistant",
            "delete memory",
        )
    finally:
        builtins.input = original_input

    assert len(assistant.calls) == 2

    first = assistant.calls[0]
    second = assistant.calls[1]

    assert first["kwargs"].get("confirmation_id") is None
    assert second["kwargs"]["confirmation_id"] == (
        "confirm-no-reprocess"
    )

    assert first["message"].content == second["message"].content
