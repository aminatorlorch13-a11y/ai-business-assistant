"""Transport-agnostic voice-session state machine owned by Assistant Core.

This module contains no network, audio, browser, subprocess, or provider I/O.
Transport adapters consume its state/transition results and perform side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock


class VoiceSessionState(str, Enum):
    """States for a continuously available assistant voice session."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    SLEEPING = "sleeping"


class VoiceSessionEvent(str, Enum):
    """State-machine events accepted by the Assistant Core."""

    START_LISTENING = "start_listening"
    START_PROCESSING = "start_processing"
    START_SPEAKING = "start_speaking"
    FINISH_SPEAKING = "finish_speaking"
    STOP = "stop"
    SLEEP = "sleep"
    WAKE = "wake"


@dataclass(frozen=True)
class VoiceStateTransition:
    """Immutable result of one accepted state transition."""

    previous: VoiceSessionState
    current: VoiceSessionState
    event: VoiceSessionEvent
    revision: int
    operation_token: int | None = None
    interrupted: bool = False


class VoiceStateError(RuntimeError):
    """Raised when an event is not valid for the current state."""


class StaleVoiceOperationError(VoiceStateError):
    """Raised when an old asynchronous operation tries to complete."""


class VoiceSessionStateMachine:
    """Thread-safe, I/O-free lifecycle state machine for one voice session.

    The machine owns lifecycle truth. It does not start/stop microphones,
    speech engines, WebSockets, or AI providers. Adapters should perform those
    side effects only after inspecting an accepted transition.

    ``revision`` changes for every accepted lifecycle transition. Processing
    and speaking operations also receive monotonically increasing operation
    tokens. A token becomes invalid when STOP or SLEEP interrupts the active
    operation, preventing stale asynchronous completions from resurrecting a
    session after a newer command.
    """

    def __init__(self, state: VoiceSessionState = VoiceSessionState.IDLE) -> None:
        if not isinstance(state, VoiceSessionState):
            raise TypeError("state must be a VoiceSessionState.")

        self._state = state
        self._revision = 0
        self._next_operation_token = 0
        self._active_operation_token: int | None = None
        self._lock = RLock()

    @property
    def state(self) -> VoiceSessionState:
        with self._lock:
            return self._state

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def active_operation_token(self) -> int | None:
        with self._lock:
            return self._active_operation_token

    def start_listening(self) -> VoiceStateTransition:
        return self._transition(
            VoiceSessionEvent.START_LISTENING,
            {VoiceSessionState.IDLE, VoiceSessionState.LISTENING},
            VoiceSessionState.LISTENING,
        )

    def start_processing(self) -> VoiceStateTransition:
        with self._lock:
            self._require_state(VoiceSessionState.LISTENING)
            token = self._new_operation_token()
            return self._commit(
                VoiceSessionEvent.START_PROCESSING,
                VoiceSessionState.PROCESSING,
                operation_token=token,
            )

    def start_speaking(self, operation_token: int | None = None) -> VoiceStateTransition:
        with self._lock:
            self._require_state(VoiceSessionState.PROCESSING)
            self._require_active_token(operation_token)
            return self._commit(
                VoiceSessionEvent.START_SPEAKING,
                VoiceSessionState.SPEAKING,
                operation_token=self._active_operation_token,
            )

    def finish_speaking(self, operation_token: int | None = None) -> VoiceStateTransition:
        with self._lock:
            self._require_state(VoiceSessionState.SPEAKING)
            self._require_active_token(operation_token)
            transition = self._commit(
                VoiceSessionEvent.FINISH_SPEAKING,
                VoiceSessionState.LISTENING,
                operation_token=self._active_operation_token,
            )
            self._active_operation_token = None
            return transition

    def stop(self) -> VoiceStateTransition:
        """Interrupt active work and return to listening; never shuts down."""
        with self._lock:
            if self._state == VoiceSessionState.SLEEPING:
                raise VoiceStateError("Cannot stop a sleeping voice session.")

            interrupted = self._state in {
                VoiceSessionState.PROCESSING,
                VoiceSessionState.SPEAKING,
            }
            self._active_operation_token = None
            return self._commit(
                VoiceSessionEvent.STOP,
                VoiceSessionState.LISTENING,
                interrupted=interrupted,
            )

    def sleep(self) -> VoiceStateTransition:
        """Explicitly put the session to sleep and invalidate active work."""
        with self._lock:
            if self._state == VoiceSessionState.SLEEPING:
                raise VoiceStateError("Voice session is already sleeping.")

            self._active_operation_token = None
            return self._commit(
                VoiceSessionEvent.SLEEP,
                VoiceSessionState.SLEEPING,
            )

    def wake(self) -> VoiceStateTransition:
        """Explicitly wake a sleeping session into listening mode."""
        return self._transition(
            VoiceSessionEvent.WAKE,
            {VoiceSessionState.SLEEPING},
            VoiceSessionState.LISTENING,
        )

    def is_operation_current(self, operation_token: int) -> bool:
        """Return whether a token still owns the current active operation."""
        if not isinstance(operation_token, int) or isinstance(operation_token, bool):
            raise TypeError("operation_token must be an integer.")

        with self._lock:
            return (
                self._active_operation_token == operation_token
                and self._state in {
                    VoiceSessionState.PROCESSING,
                    VoiceSessionState.SPEAKING,
                }
            )

    def require_operation_current(self, operation_token: int) -> None:
        if not self.is_operation_current(operation_token):
            raise StaleVoiceOperationError("Voice operation is no longer current.")

    def _transition(
        self,
        event: VoiceSessionEvent,
        allowed: set[VoiceSessionState],
        target: VoiceSessionState,
    ) -> VoiceStateTransition:
        with self._lock:
            if self._state not in allowed:
                self._raise_invalid(event, allowed)
            return self._commit(event, target)

    def _commit(
        self,
        event: VoiceSessionEvent,
        target: VoiceSessionState,
        *,
        operation_token: int | None = None,
        interrupted: bool = False,
    ) -> VoiceStateTransition:
        previous = self._state
        self._state = target
        self._revision += 1
        return VoiceStateTransition(
            previous=previous,
            current=target,
            event=event,
            revision=self._revision,
            operation_token=operation_token,
            interrupted=interrupted,
        )

    def _new_operation_token(self) -> int:
        self._next_operation_token += 1
        self._active_operation_token = self._next_operation_token
        return self._active_operation_token

    def _require_state(self, expected: VoiceSessionState) -> None:
        if self._state != expected:
            raise VoiceStateError(
                f"Expected {expected.value}, but session is {self._state.value}."
            )

    def _require_active_token(self, operation_token: int | None) -> None:
        if operation_token is not None and operation_token != self._active_operation_token:
            raise StaleVoiceOperationError("Voice operation token is stale.")
        if self._active_operation_token is None:
            raise StaleVoiceOperationError("No active voice operation exists.")

    def _raise_invalid(
        self,
        event: VoiceSessionEvent,
        allowed: set[VoiceSessionState],
    ) -> None:
        expected = ", ".join(sorted(state.value for state in allowed))
        raise VoiceStateError(
            f"Cannot apply {event.value} from {self._state.value}; "
            f"allowed states: {expected}."
        )
