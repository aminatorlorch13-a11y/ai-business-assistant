from pathlib import Path

from app.voice.conversation import ConversationState
from app.voice.session import ConversationSession


CLI_PATH = Path("app/cli/main_voice.py")


def test_cli_shutdown_commands_are_explicitly_exit_and_quit_only():
    source = CLI_PATH.read_text()

    assert 'if text.strip().lower() in {"exit", "quit"}:' in source


def test_cli_does_not_treat_stop_as_a_shutdown_command():
    source = CLI_PATH.read_text()

    assert 'if text.strip().lower() in {"exit", "quit", "stop"}:' not in source


def test_stop_is_not_a_conversation_shutdown_command_in_the_voice_pipeline():
    source = CLI_PATH.read_text()

    termination_line = 'if text.strip().lower() in {"exit", "quit"}:'

    assert termination_line in source
    assert '"stop"' not in termination_line


def test_internal_session_stop_remains_an_explicit_lifecycle_operation():
    session = ConversationSession()

    session.start_listening()
    session.stop()

    assert session.state is ConversationState.ENDED


def test_waiting_session_can_continue_after_normal_conversation_turn():
    session = ConversationSession()

    session.start_listening()
    session.start_processing()
    session.start_speaking()
    session.wait_for_input()

    session.start_listening()

    assert session.state is ConversationState.LISTENING
