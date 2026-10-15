import pytest

from app.ai.provider_request_budget import (
    MAX_PROVIDER_TEXT_CHARS,
    validate_provider_request_size,
)


def test_accepts_request_within_budget():
    validate_provider_request_size(
        instructions="system instructions",
        user_content="owner message",
        structured_output="schema",
    )


def test_rejects_request_over_budget_without_truncating_input():
    owner_message = "x" * MAX_PROVIDER_TEXT_CHARS
    with pytest.raises(ValueError, match="text-size budget"):
        validate_provider_request_size(
            instructions="instructions",
            user_content=owner_message,
        )


def test_rejects_non_string_request_fields():
    with pytest.raises(TypeError, match="must be strings"):
        validate_provider_request_size(
            instructions="instructions",
            user_content=None,  # type: ignore[arg-type]
        )


def test_rejects_invalid_budget():
    with pytest.raises(ValueError, match="maximum"):
        validate_provider_request_size(
            instructions="system",
            user_content="message",
            maximum=100,
        )
