from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GroqConfig:
    api_key: str
    model: str = "openai/gpt-oss-120b"
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 60.0

    @classmethod
    def from_environment(cls) -> "GroqConfig":
        api_key = os.getenv("GROQ_API_KEY", "").strip()

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is required."
            )

        model = os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-120b",
        ).strip()

        base_url = os.getenv(
            "GROQ_BASE_URL",
            "https://api.groq.com/openai/v1",
        ).strip().rstrip("/")

        timeout_raw = os.getenv(
            "GROQ_TIMEOUT_SECONDS",
            "60",
        ).strip()

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise RuntimeError(
                "GROQ_TIMEOUT_SECONDS must be numeric."
            ) from exc

        if timeout_seconds <= 0:
            raise RuntimeError(
                "GROQ_TIMEOUT_SECONDS must be greater than zero."
            )

        if not model:
            raise RuntimeError(
                "GROQ_MODEL must not be empty."
            )

        if not base_url:
            raise RuntimeError(
                "GROQ_BASE_URL must not be empty."
            )

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
