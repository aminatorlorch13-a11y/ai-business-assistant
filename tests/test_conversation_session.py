import pytest

from app.voice.conversation import ConversationState
from app.voice.session import ConversationSession


def test_session_starts_idle():
    session = ConversationSession()

    assert session.state is ConversationState.IDLE


def test_session_follows_normal_conversation_flow():
    session = ConversationSession()

    session.start_listening()
    assert session.state is ConversationState.LISTENING

    session.start_processing()
    assert session.state is ConversationState.PROCESSING

    session.start_speaking()
    assert session.state is ConversationState.SPEAKING

    session.wait_for_input()
    assert session.state is ConversationState.WAITING_FOR_INPUT

    session.start_listening()
    assert session.state is ConversationState.LISTENING


def test_session_can_stop_from_waiting_for_input():
    session = ConversationSession()
    session.start_listening()
    session.start_processing()
    session.start_speaking()
    session.wait_for_input()

    session.stop()

    assert session.state is ConversationState.ENDED


def test_stop_is_idempotent_after_session_has_ended():
    session = ConversationSession()

    session.stop()
    session.stop()

    assert session.state is ConversationState.ENDED


@pytest.mark.parametrize(
    "method_name",
    [
        "start_processing",
        "start_speaking",
        "wait_for_input",
    ],
)
def test_invalid_forward_transitions_are_rejected(method_name):
    session = ConversationSession()

    with pytest.raises(RuntimeError):
        getattr(session, method_name)()


def test_listening_cannot_start_while_processing():
    session = ConversationSession()
    session.start_listening()
    session.start_processing()

    with pytest.raises(RuntimeError):
        session.start_listening()


def test_speaking_cannot_start_before_processing():
    session = ConversationSession()
    session.start_listening()

    with pytest.raises(RuntimeError):
        session.start_speaking()


def test_waiting_for_input_cannot_start_before_speaking():
    session = ConversationSession()
    session.start_listening()
    session.start_processing()

    with pytest.raises(RuntimeError):
        session.wait_for_input()


def test_error_state_can_recover_to_input():
    session = ConversationSession()
    session.start_listening()

    session.fail()

    assert session.state is ConversationState.ERROR

    session.recover_to_input()

    assert session.state is ConversationState.WAITING_FOR_INPUT


def test_error_state_rejects_normal_progression():
    session = ConversationSession()
    session.fail()

    with pytest.raises(RuntimeError):
        session.start_processing()


def test_ended_session_cannot_restart():
    session = ConversationSession()
    session.stop()

    with pytest.raises(RuntimeError):
        session.start_listening()


def test_ended_session_cannot_recover_or_progress():
    session = ConversationSession()
    session.stop()

    with pytest.raises(RuntimeError):
        session.start_processing()

    with pytest.raises(RuntimeError):
        session.start_speaking()

    with pytest.raises(RuntimeError):
        session.wait_for_input()

    with pytest.raises(RuntimeError):
        session.recover_to_input()


def test_ended_session_cannot_fail():
    session = ConversationSession()
    session.stop()

    with pytest.raises(RuntimeError):
        session.fail()


def test_stop_can_interrupt_listening():
    session = ConversationSession()
    session.start_listening()

    session.stop()

    assert session.state is ConversationState.ENDED


def test_stop_can_interrupt_processing():
    session = ConversationSession()
    session.start_listening()
    session.start_processing()

    session.stop()

    assert session.state is ConversationState.ENDED


def test_stop_can_interrupt_speaking():
    session = ConversationSession()
    session.start_listening()
    session.start_processing()
    session.start_speaking()

    session.stop()

    assert session.state is ConversationState.ENDED


def test_error_state_can_be_recovered():
    session = ConversationSession()
    session.fail()

    assert session.state is ConversationState.ERROR

    session.recover_to_input()

    assert session.state is ConversationState.WAITING_FOR_INPUT
