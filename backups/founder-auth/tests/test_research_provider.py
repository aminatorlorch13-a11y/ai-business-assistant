import pytest

from app.research.provider import ResearchProvider
from app.research.request import ResearchRequest
from app.research.result import ResearchResult


class StubResearchProvider(ResearchProvider):
    def research(self, request: ResearchRequest) -> ResearchResult:
        return ResearchResult(
            business_id=request.business_id,
            query=request.query,
            summary="Stub research completed.",
        )


def make_request() -> ResearchRequest:
    return ResearchRequest(
        business_id="business-001",
        query="Research recent market trends.",
        category="general",
    )


def test_research_provider_is_abstract():
    with pytest.raises(TypeError):
        ResearchProvider()


def test_stub_provider_implements_research_contract():
    provider = StubResearchProvider()

    result = provider.research(make_request())

    assert isinstance(result, ResearchResult)
    assert result.business_id == "business-001"
    assert result.query == "Research recent market trends."
    assert result.summary == "Stub research completed."
