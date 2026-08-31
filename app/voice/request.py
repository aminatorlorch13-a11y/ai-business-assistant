from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechRequest:
    """A request to convert assistant text into spoken audio."""

    text: str
    voice: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string.")

        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice must be a non-empty string.")
