import threading

import pytest

from app.assistant.voice_state import (
    StaleVoiceOperationError,
    VoiceSessionEvent,
    VoiceSessionState,
    VoiceSessionStateMachine,
    VoiceStateError,
)


def test_initial_state_is_idle():
    machine = VoiceSessionStateMachine()
    assert machine.state is VoiceSessionState.IDLE
    assert machine.revision == 0
    assert machine.active_operation_token is None


def test_normal_voice_cycle_is_listening_processing_speaking_listening():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    processing = machine.start_processing()
    speaking = machine.start_speaking(processing.operation_token)
    finished = machine.finish_speaking(speaking.operation_token)
    assert finished.current is VoiceSessionState.LISTENING


def test_stop_during_processing_returns_to_listening_and_interrupts():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    machine.start_processing()
    transition = machine.stop()
    assert transition.event is VoiceSessionEvent.STOP
    assert transition.previous is VoiceSessionState.PROCESSING
    assert transition.current is VoiceSessionState.LISTENING
    assert transition.interrupted is True
    assert machine.active_operation_token is None


def test_stop_during_speaking_returns_to_listening_and_interrupts():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    processing = machine.start_processing()
    machine.start_speaking(processing.operation_token)
    transition = machine.stop()
    assert transition.previous is VoiceSessionState.SPEAKING
    assert transition.current is VoiceSessionState.LISTENING
    assert transition.interrupted is True


def test_stop_never_creates_shutdown_or_ended_state():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    machine.stop()
    assert machine.state is VoiceSessionState.LISTENING
    assert all("end" not in state.value for state in VoiceSessionState)


def test_stop_from_listening_is_safe_and_remains_listening():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    transition = machine.stop()
    assert transition.current is VoiceSessionState.LISTENING
    assert transition.interrupted is False


def test_sleep_is_explicit_and_wake_returns_to_listening():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    sleeping = machine.sleep()
    waking = machine.wake()
    assert sleeping.current is VoiceSessionState.SLEEPING
    assert waking.current is VoiceSessionState.LISTENING


def test_sleep_invalidates_processing_operation():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    processing = machine.start_processing()
    machine.sleep()
    assert machine.state is VoiceSessionState.SLEEPING
    assert machine.active_operation_token is None
    with pytest.raises(StaleVoiceOperationError):
        machine.require_operation_current(processing.operation_token)


def test_stop_invalidates_processing_operation():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    processing = machine.start_processing()
    machine.stop()
    with pytest.raises(StaleVoiceOperationError):
        machine.require_operation_current(processing.operation_token)


def test_stale_processing_token_cannot_start_speaking():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    old = machine.start_processing()
    machine.stop()
    machine.start_processing()
    with pytest.raises(StaleVoiceOperationError):
        machine.start_speaking(old.operation_token)


def test_stale_speaking_completion_cannot_finish_new_operation():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    old_processing = machine.start_processing()
    old_speaking = machine.start_speaking(old_processing.operation_token)
    machine.stop()
    new_processing = machine.start_processing()
    new_speaking = machine.start_speaking(new_processing.operation_token)
    with pytest.raises(StaleVoiceOperationError):
        machine.finish_speaking(old_speaking.operation_token)
    assert machine.state is VoiceSessionState.SPEAKING
    machine.finish_speaking(new_speaking.operation_token)
    assert machine.state is VoiceSessionState.LISTENING


def test_operation_tokens_are_monotonic_and_unique():
    machine = VoiceSessionStateMachine()
    tokens = []
    for _ in range(20):
        machine.start_listening()
        transition = machine.start_processing()
        tokens.append(transition.operation_token)
        machine.stop()
    assert tokens == sorted(tokens)
    assert len(tokens) == len(set(tokens))


def test_revision_increases_for_every_accepted_transition():
    machine = VoiceSessionStateMachine()
    revisions = [machine.start_listening().revision, machine.start_processing().revision]
    processing = machine.active_operation_token
    revisions.append(machine.start_speaking(processing).revision)
    revisions.append(machine.stop().revision)
    revisions.append(machine.sleep().revision)
    revisions.append(machine.wake().revision)
    assert revisions == list(range(1, len(revisions) + 1))


@pytest.mark.parametrize(
    "operation",
    [
        lambda m: m.start_processing(),
        lambda m: m.start_speaking(1),
        lambda m: m.finish_speaking(1),
        lambda m: m.wake(),
    ],
)
def test_invalid_transitions_are_rejected(operation):
    machine = VoiceSessionStateMachine()
    with pytest.raises(VoiceStateError):
        operation(machine)


def test_sleeping_session_rejects_stop_until_explicit_wake():
    machine = VoiceSessionStateMachine()
    machine.sleep()
    with pytest.raises(VoiceStateError):
        machine.stop()
    machine.wake()
    machine.stop()
    assert machine.state is VoiceSessionState.LISTENING


def test_sleeping_session_cannot_start_processing_or_speaking():
    machine = VoiceSessionStateMachine()
    machine.sleep()
    with pytest.raises(VoiceStateError):
        machine.start_processing()
    with pytest.raises(VoiceStateError):
        machine.start_speaking(1)


def test_token_current_check_rejects_invalid_token_types():
    machine = VoiceSessionStateMachine()
    with pytest.raises(TypeError):
        machine.is_operation_current(True)
    with pytest.raises(TypeError):
        machine.is_operation_current("1")


def test_concurrent_stop_calls_are_serialized_and_never_leave_active_work():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    machine.start_processing()
    transitions = []
    errors = []
    lock = threading.Lock()

    def stop_worker():
        try:
            result = machine.stop()
            with lock:
                transitions.append(result)
        except Exception as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=stop_worker) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert machine.state is VoiceSessionState.LISTENING
    assert machine.active_operation_token is None
    assert len(transitions) == 50


def test_concurrent_start_and_stop_never_exposes_processing_without_a_current_token():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            machine.start_processing()
            machine.stop()
        except VoiceStateError:
            pass
        except Exception as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    if machine.state is VoiceSessionState.PROCESSING:
        assert machine.active_operation_token is not None
    else:
        assert machine.active_operation_token is None


def test_stale_completion_attack_after_many_stop_restart_cycles():
    machine = VoiceSessionStateMachine()
    machine.start_listening()
    stale = machine.start_processing()
    machine.stop()
    for _ in range(100):
        machine.start_processing()
        machine.stop()
    with pytest.raises(StaleVoiceOperationError):
        machine.require_operation_current(stale.operation_token)
    assert machine.state is VoiceSessionState.LISTENING
