from unittest.mock import Mock, patch
import threading

import pytest

from app.voice.engine import SpeechEngine
from app.voice.local_engine import AndroidSpeechEngine
from app.voice.request import SpeechRequest


def test_speech_engine_exposes_explicit_current_speech_cancellation():
    assert hasattr(SpeechEngine, "cancel_current")


def test_android_speech_engine_cancellation_is_safe_when_nothing_is_speaking():
    engine = AndroidSpeechEngine()

    with patch("subprocess.Popen") as popen:
        engine.cancel_current()

    popen.assert_not_called()


def test_android_speech_engine_tracks_active_process_for_cancellation():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = 0
    process.wait.return_value = 0

    request = SpeechRequest(
        text="Hello",
        voice="male",
        speed=1.0,
    )

    with patch("subprocess.Popen", return_value=process) as popen:
        engine.speak(request)

    popen.assert_called_once()
    process.wait.assert_called_once()
    assert engine._active_process is None


def test_android_speech_engine_cancel_terminates_active_process():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=process):
        engine._active_process = process
        engine.cancel_current()

    process.terminate.assert_called_once()
    assert engine._active_process is None


def test_android_speech_engine_cancel_does_not_affect_finished_process():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = 0

    engine._active_process = process
    engine.cancel_current()

    process.terminate.assert_not_called()
    assert engine._active_process is None


def test_cancel_current_does_not_change_conversation_session_state():
    from app.voice.conversation import ConversationState
    from app.voice.session import ConversationSession

    session = ConversationSession()
    session.start_listening()
    session.start_processing()
    session.start_speaking()

    engine = AndroidSpeechEngine()
    engine.cancel_current()

    assert session.state is ConversationState.SPEAKING


def test_cancel_current_does_not_mean_shutdown():
    engine = AndroidSpeechEngine()

    assert callable(getattr(engine, "cancel_current", None))


def test_speech_request_remains_required_for_speech():
    engine = AndroidSpeechEngine()

    with pytest.raises(TypeError, match="SpeechRequest"):
        engine.speak("stop speaking")


def test_cancel_current_is_safe_when_process_disappears_before_termination():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = None
    process.terminate.side_effect = ProcessLookupError

    engine._active_process = process

    engine.cancel_current()

    process.terminate.assert_called_once()
    assert engine._active_process is None


def test_cancel_current_can_be_called_repeatedly_safely():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = None

    engine._active_process = process

    engine.cancel_current()
    engine.cancel_current()

    process.terminate.assert_called_once()
    assert engine._active_process is None


def test_cancel_current_is_race_safe_against_repeated_cancellation_calls():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = None

    engine._active_process = process

    threads = [
        threading.Thread(target=engine.cancel_current)
        for _ in range(20)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert engine._active_process is None
    assert process.terminate.call_count >= 1


def test_concurrent_cancellation_has_single_termination_owner():
    engine = AndroidSpeechEngine()

    process = Mock()
    process.poll.return_value = None

    entered = threading.Event()
    release = threading.Event()

    termination_count = 0
    termination_lock = threading.Lock()

    def blocked_terminate():
        nonlocal termination_count

        entered.set()
        release.wait(timeout=2)

        with termination_lock:
            termination_count += 1

    process.terminate.side_effect = blocked_terminate
    engine._active_process = process

    first = threading.Thread(target=engine.cancel_current)
    second = threading.Thread(target=engine.cancel_current)

    first.start()
    assert entered.wait(timeout=2)

    second.start()

    release.set()

    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()

    # Exactly one cancellation operation must own the active process.
    assert termination_count == 1

    # The process termination method itself must have been entered once.
    process.terminate.assert_called_once()

    # Cancellation must leave no active process behind.
    assert engine._active_process is None


def test_cancel_current_does_not_terminate_a_newer_process():
    engine = AndroidSpeechEngine()

    old_process = Mock()
    old_process.poll.return_value = None

    new_process = Mock()
    new_process.poll.return_value = None

    engine._active_process = old_process

    # Simulate another speech operation replacing the active process
    # before cancellation observes it.
    engine._active_process = new_process

    engine.cancel_current()

    old_process.terminate.assert_not_called()
    new_process.terminate.assert_called_once()
    assert engine._active_process is None


def test_concurrent_cancellation_never_terminates_a_replaced_process():
    engine = AndroidSpeechEngine()

    old_process = Mock()
    old_process.poll.return_value = None

    new_process = Mock()
    new_process.poll.return_value = None

    entered = threading.Event()
    release = threading.Event()

    def blocked_poll():
        entered.set()
        release.wait(timeout=2)
        return None

    old_process.poll.side_effect = blocked_poll

    engine._active_process = old_process

    thread = threading.Thread(target=engine.cancel_current)
    thread.start()

    assert entered.wait(timeout=2)

    # Simulate a new speech operation becoming active while the
    # cancellation operation is still inspecting the old process.
    engine._active_process = new_process

    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()

    # The cancellation operation must only act on the process it
    # originally captured.
    old_process.terminate.assert_called_once()

    # Most importantly, it must not accidentally clear the newer
    # process reference.
    assert engine._active_process is new_process
