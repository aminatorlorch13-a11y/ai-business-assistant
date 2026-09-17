from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str = "gpt-5.6"
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "OpenAIConfig":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required."
            )

        model = os.getenv(
            "OPENAI_MODEL",
            "gpt-5.6",
        ).strip()

        base_url = os.getenv(
            "OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        ).strip().rstrip("/")

        timeout_raw = os.getenv(
            "OPENAI_TIMEOUT_SECONDS",
            "60",
        ).strip()

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise RuntimeError(
                "OPENAI_TIMEOUT_SECONDS must be numeric."
            ) from exc

        if timeout_seconds <= 0:
            raise RuntimeError(
                "OPENAI_TIMEOUT_SECONDS must be greater than zero."
            )

        if not model:
            raise RuntimeError(
                "OPENAI_MODEL must not be empty."
            )

        if not base_url:
            raise RuntimeError(
                "OPENAI_BASE_URL must not be empty."
            )

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
