from dataclasses import dataclass

from app.voice.conversation import ConversationState


@dataclass
class ConversationSession:
    """Owns the lifecycle state of one assistant conversation."""

    state: ConversationState = ConversationState.IDLE

    def start_listening(self) -> None:
        """Move an idle or waiting session into listening."""
        if self.state not in {
            ConversationState.IDLE,
            ConversationState.WAITING_FOR_INPUT,
        }:
            raise RuntimeError(
                f"Cannot start listening from {self.state.value}."
            )

        self.state = ConversationState.LISTENING

    def start_processing(self) -> None:
        """Move a listening session into processing."""
        self._require(ConversationState.LISTENING)
        self.state = ConversationState.PROCESSING

    def start_speaking(self) -> None:
        """Move a processed session into speaking."""
        self._require(ConversationState.PROCESSING)
        self.state = ConversationState.SPEAKING

    def wait_for_input(self) -> None:
        """Move a speaking session into the next input phase."""
        self._require(ConversationState.SPEAKING)
        self.state = ConversationState.WAITING_FOR_INPUT

    def stop(self) -> None:
        """End the session through the explicit stopping state."""
        if self.state == ConversationState.ENDED:
            return

        if self.state != ConversationState.STOPPING:
            self.state = ConversationState.STOPPING

        self.state = ConversationState.ENDED

    def fail(self) -> None:
        """Move the session into its terminal error state."""
        if self.state == ConversationState.ENDED:
            raise RuntimeError("Cannot fail an ended conversation.")

        self.state = ConversationState.ERROR

    def recover_to_input(self) -> None:
        """Recover from an error by returning to the input phase."""
        self._require(ConversationState.ERROR)
        self.state = ConversationState.WAITING_FOR_INPUT

    def _require(self, expected: ConversationState) -> None:
        if self.state != expected:
            raise RuntimeError(
                f"Expected {expected.value}, "
                f"but session is {self.state.value}."
            )
