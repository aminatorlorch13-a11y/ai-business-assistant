from abc import ABC, abstractmethod

from app.research.request import ResearchRequest
from app.research.result import ResearchResult


class ResearchProvider(ABC):
    """Interface for providers capable of performing external research."""

    @abstractmethod
    def research(self, request: ResearchRequest) -> ResearchResult:
        """Perform research for a validated request."""
        raise NotImplementedError
