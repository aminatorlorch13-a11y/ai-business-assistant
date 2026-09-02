from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechInput:
    """Validated text produced from one user speech recognition result."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string.")
