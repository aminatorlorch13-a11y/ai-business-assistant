from abc import ABC, abstractmethod

from app.voice.request import SpeechRequest


class SpeechEngine(ABC):
    """Interface implemented by every speech engine."""

    def validate_request(self, request: SpeechRequest) -> None:
        """Reject expressive features this engine has not implemented."""

        if not isinstance(request, SpeechRequest):
            raise TypeError("request must be a SpeechRequest.")

        unsupported = []

        if request.emotion != "neutral":
            unsupported.append("emotion")

        if request.delivery != "normal":
            unsupported.append("delivery")

        if request.pitch is not None:
            unsupported.append("pitch")

        if request.vocalizations:
            unsupported.append("vocalizations")

        if unsupported:
            features = ", ".join(unsupported)
            raise NotImplementedError(
                f"{type(self).__name__} does not support these "
                f"speech features: {features}."
            )

    @abstractmethod
    def speak(self, request: SpeechRequest) -> None:
        """Speak the supplied speech request."""
        raise NotImplementedError

    @abstractmethod
    def cancel_current(self) -> None:
        """Cancel the currently active speech output, if any."""
        raise NotImplementedError
