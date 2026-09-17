class ResearchProviderError(Exception):
    """Base error for failures originating from a research provider."""


class ResearchProviderUnavailable(ResearchProviderError):
    """Raised when the research provider is temporarily unavailable."""


class ResearchProviderTimeout(ResearchProviderError):
    """Raised when the research provider exceeds its allowed response time."""
