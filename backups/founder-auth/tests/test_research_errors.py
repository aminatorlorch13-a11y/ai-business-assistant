import pytest

from app.research.errors import (
    ResearchProviderError,
    ResearchProviderTimeout,
    ResearchProviderUnavailable,
)


def test_provider_unavailable_is_provider_error():
    error = ResearchProviderUnavailable("Provider unavailable.")

    assert isinstance(error, ResearchProviderError)


def test_provider_timeout_is_provider_error():
    error = ResearchProviderTimeout("Provider timed out.")

    assert isinstance(error, ResearchProviderError)


@pytest.mark.parametrize(
    "error_type",
    [
        ResearchProviderError,
        ResearchProviderUnavailable,
        ResearchProviderTimeout,
    ],
)
def test_research_provider_errors_are_exceptions(error_type):
    error = error_type("Research provider failure.")

    assert isinstance(error, Exception)


def test_provider_unavailable_preserves_message():
    error = ResearchProviderUnavailable("Service temporarily unavailable.")

    assert str(error) == "Service temporarily unavailable."


def test_provider_timeout_preserves_message():
    error = ResearchProviderTimeout("Research request timed out.")

    assert str(error) == "Research request timed out."
