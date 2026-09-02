from enum import Enum


class ConversationState(Enum):
    """Lifecycle states for one assistant conversation."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    WAITING_FOR_INPUT = "waiting_for_input"
    STOPPING = "stopping"
    ENDED = "ended"
    ERROR = "error"
