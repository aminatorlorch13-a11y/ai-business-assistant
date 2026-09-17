import pytest

from app.research.policy import ResearchPolicy
from app.research.request import (
    SUPPORTED_RESEARCH_CATEGORIES,
    ResearchRequest,
)
from app.research.result import (
    ResearchFinding,
    ResearchResult,
    ResearchSource,
)


def make_request(
    category: str = "general",
) -> ResearchRequest:
    return ResearchRequest(
        business_id="business-001",
        query="Research recent market trends.",
        category=category,
    )


def make_source() -> ResearchSource:
    return ResearchSource(
        title="Market Report",
        url="https://example.com/report",
        publisher="Example Publisher",
        retrieved_at="2026-09-01T10:00:00+02:00",
    )


def make_finding() -> ResearchFinding:
    return ResearchFinding(
        statement="Demand increased in the target market.",
        significance="This may indicate a growth opportunity.",
    )


def test_research_request_accepts_valid_input():
    request = make_request()

    assert request.business_id == "business-001"
    assert request.query == "Research recent market trends."
    assert request.category == "general"
    assert request.requester == "business_owner"


@pytest.mark.parametrize(
    "business_id",
    ["", "   ", None, 123],
)
def test_research_request_rejects_invalid_business_id(
    business_id,
):
    with pytest.raises(
        (TypeError, ValueError),
        match="business_id",
    ):
        ResearchRequest(
            business_id=business_id,
            query="Research something.",
        )


@pytest.mark.parametrize(
    "query",
    ["", "   ", None, 123],
)
def test_research_request_rejects_invalid_query(query):
    with pytest.raises(
        (TypeError, ValueError),
        match="query",
    ):
        ResearchRequest(
            business_id="business-001",
            query=query,
        )


@pytest.mark.parametrize(
    "category",
    ["", "   ", None, 123, "unknown"],
)
def test_research_request_rejects_invalid_category(
    category,
):
    with pytest.raises(
        (TypeError, ValueError),
        match="category",
    ):
        ResearchRequest(
            business_id="business-001",
            query="Research something.",
            category=category,
        )


def test_supported_research_categories_are_explicit():
    assert SUPPORTED_RESEARCH_CATEGORIES == {
        "general",
        "market",
        "competitor",
        "industry",
        "product",
        "news",
        "technology",
    }


def test_research_source_accepts_valid_input():
    source = make_source()

    assert source.title == "Market Report"
    assert source.url == "https://example.com/report"
    assert source.publisher == "Example Publisher"
    assert source.retrieved_at == (
        "2026-09-01T10:00:00+02:00"
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "title",
        "url",
        "publisher",
        "retrieved_at",
    ],
)
def test_research_source_rejects_invalid_fields(
    field_name,
):
    values = {
        "title": "Title",
        "url": "https://example.com",
        "publisher": "Publisher",
        "retrieved_at": "2026-09-01T10:00:00+02:00",
    }

    values[field_name] = ""

    with pytest.raises(
        (TypeError, ValueError),
        match=field_name,
    ):
        ResearchSource(**values)


def test_research_finding_accepts_valid_input():
    finding = make_finding()

    assert finding.statement == (
        "Demand increased in the target market."
    )

    assert finding.significance == (
        "This may indicate a growth opportunity."
    )


@pytest.mark.parametrize(
    "statement",
    ["", "   ", None, 123],
)
def test_research_finding_rejects_invalid_statement(
    statement,
):
    with pytest.raises(
        (TypeError, ValueError),
        match="statement",
    ):
        ResearchFinding(
            statement=statement,
            significance="Important.",
        )


@pytest.mark.parametrize(
    "significance",
    ["", "   ", None, 123],
)
def test_research_finding_rejects_invalid_significance(
    significance,
):
    with pytest.raises(
        (TypeError, ValueError),
        match="significance",
    ):
        ResearchFinding(
            statement="Finding.",
            significance=significance,
        )


def test_research_result_accepts_structured_evidence():
    result = ResearchResult(
        business_id="business-001",
        query="Research recent market trends.",
        summary=(
            "Several relevant developments were identified."
        ),
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=(
            "Some market data may lag.",
        ),
    )

    assert result.business_id == "business-001"
    assert len(result.findings) == 1
    assert len(result.sources) == 1
    assert len(result.limitations) == 1


def test_research_result_supports_empty_evidence():
    result = ResearchResult(
        business_id="business-001",
        query="Research something.",
        summary="Research completed.",
    )

    assert result.findings == ()
    assert result.sources == ()
    assert result.limitations == ()


def test_research_result_is_immutable():
    result = ResearchResult(
        business_id="business-001",
        query="Research something.",
        summary="Research completed.",
    )

    with pytest.raises(AttributeError):
        result.summary = "Changed."


@pytest.mark.parametrize(
    "field_name",
    [
        "findings",
        "sources",
        "limitations",
    ],
)
def test_research_result_rejects_non_tuple_collections(
    field_name,
):
    values = {
        "findings": (),
        "sources": (),
        "limitations": (),
    }

    values[field_name] = []

    with pytest.raises(
        TypeError,
        match=field_name,
    ):
        ResearchResult(
            business_id="business-001",
            query="Research something.",
            summary="Research completed.",
            **values,
        )


def test_research_result_rejects_invalid_findings():
    with pytest.raises(
        TypeError,
        match="each finding",
    ):
        ResearchResult(
            business_id="business-001",
            query="Research something.",
            summary="Research completed.",
            findings=("invalid",),
        )


def test_research_result_rejects_invalid_sources():
    with pytest.raises(
        TypeError,
        match="each source",
    ):
        ResearchResult(
            business_id="business-001",
            query="Research something.",
            summary="Research completed.",
            sources=("invalid",),
        )


def test_research_result_rejects_invalid_limitations():
    with pytest.raises(
        TypeError,
        match="each limitation",
    ):
        ResearchResult(
            business_id="business-001",
            query="Research something.",
            summary="Research completed.",
            limitations=(123,),
        )


def test_research_policy_denies_research_by_default():
    policy = ResearchPolicy()

    assert policy.allows(make_request()) is False


def test_research_policy_allows_enabled_general_research():
    policy = ResearchPolicy(
        enabled=True,
        allowed_categories=frozenset({"general"}),
    )

    assert policy.allows(make_request()) is True


def test_research_policy_denies_category_not_allowed():
    policy = ResearchPolicy(
        enabled=True,
        allowed_categories=frozenset({"general"}),
    )

    assert policy.allows(make_request("market")) is False


def test_research_policy_allows_multiple_categories():
    policy = ResearchPolicy(
        enabled=True,
        allowed_categories=frozenset(
            {
                "general",
                "market",
                "competitor",
            }
        ),
    )

    assert policy.allows(make_request("general")) is True
    assert policy.allows(make_request("market")) is True
    assert policy.allows(make_request("competitor")) is True


def test_research_policy_can_allow_all_current_categories():
    policy = ResearchPolicy(
        enabled=True,
        allowed_categories=SUPPORTED_RESEARCH_CATEGORIES,
    )

    for category in SUPPORTED_RESEARCH_CATEGORIES:
        assert policy.allows(make_request(category)) is True


@pytest.mark.parametrize(
    "enabled",
    [None, 1, 0, "true"],
)
def test_research_policy_rejects_invalid_enabled(enabled):
    with pytest.raises(
        TypeError,
        match="enabled",
    ):
        ResearchPolicy(enabled=enabled)


def test_research_policy_rejects_non_frozenset_categories():
    with pytest.raises(
        TypeError,
        match="allowed_categories",
    ):
        ResearchPolicy(
            enabled=True,
            allowed_categories={"general"},
        )


def test_research_policy_rejects_unknown_categories():
    with pytest.raises(
        ValueError,
        match="unsupported categories",
    ):
        ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset(
                {
                    "general",
                    "stock_prediction",
                }
            ),
        )


def test_research_policy_rejects_invalid_request():
    policy = ResearchPolicy(
        enabled=True,
        allowed_categories=frozenset({"general"}),
    )

    with pytest.raises(
        TypeError,
        match="ResearchRequest",
    ):
        policy.allows(object())
