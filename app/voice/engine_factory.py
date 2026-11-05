from __future__ import annotations

import os

from app.voice.engine import SpeechEngine
from app.voice.local_engine import AndroidSpeechEngine


def build_speech_engine(provider: str | None = None) -> SpeechEngine:
    selected = (
        os.getenv("AMINATION_TTS_PROVIDER", "android")
        if provider is None
        else provider
    )

    if not isinstance(selected, str):
        raise TypeError("Speech provider must be a string.")

    selected = selected.strip().lower()

    if selected == "android":
        return AndroidSpeechEngine()

    if selected == "azure":
        from app.voice.azure_engine import (
            AzureSpeechConfig,
            AzureSpeechEngine,
        )

        return AzureSpeechEngine(AzureSpeechConfig.from_environment())

    raise ValueError(
        "Unsupported speech provider. Choose 'android' or 'azure'."
    )
