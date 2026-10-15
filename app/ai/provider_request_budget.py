"""Conservative character budget for outbound AI provider requests."""

from __future__ import annotations


MAX_PROVIDER_TEXT_CHARS = 48_000
_REQUEST_OVERHEAD_RESERVE = 2_000


def validate_provider_request_size(
    *,
    instructions: str,
    user_content: str,
    structured_output: str = "",
    maximum: int = MAX_PROVIDER_TEXT_CHARS,
) -> None:
    """Reject oversized requests without silently truncating owner input.

    This is a character-count guard, not a model-token estimator.
    """
    values = (instructions, user_content, structured_output)
    if any(not isinstance(value, str) for value in values):
        raise TypeError("Provider request text fields must be strings.")
    if type(maximum) is not int or maximum <= _REQUEST_OVERHEAD_RESERVE:
        raise ValueError("maximum must be an integer greater than the overhead reserve.")

    total = sum(len(value) for value in values) + _REQUEST_OVERHEAD_RESERVE
    if total > maximum:
        raise ValueError(
            "Provider request exceeds the configured text-size budget; "
            "reduce supplied context or split the request."
        )
