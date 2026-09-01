import pytest

from app.research.briefing import (
    ResearchBriefing,
    ResearchBriefingBuilder,
)
from app.research.result import (
    ResearchFinding,
    ResearchResult,
    ResearchSource,
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


def make_result() -> ResearchResult:
    return ResearchResult(
        business_id="business-001",
        query="Research recent market trends.",
        summary="Several relevant developments were identified.",
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=("Some market data may lag.",),
    )


def test_builder_creates_owner_facing_briefing():
    briefing = ResearchBriefingBuilder().build(make_result())

    assert isinstance(briefing, ResearchBriefing)
    assert briefing.business_id == "business-001"
    assert briefing.query == "Research recent market trends."
    assert briefing.headline == (
        "Several relevant developments were identified."
    )


def test_builder_preserves_research_findings():
    result = make_result()

    briefing = ResearchBriefingBuilder().build(result)

    assert briefing.findings == result.findings


def test_builder_extracts_implications_from_findings():
    briefing = ResearchBriefingBuilder().build(make_result())

    assert briefing.implications == (
        "This may indicate a growth opportunity.",
    )


def test_builder_creates_options_without_claiming_decision():
    briefing = ResearchBriefingBuilder().build(make_result())

    assert len(briefing.options) == 1
    assert "Consider investigating or testing" in briefing.options[0]


def test_builder_preserves_limitations():
    briefing = ResearchBriefingBuilder().build(make_result())

    assert briefing.limitations == (
        "Some market data may lag.",
    )


def test_builder_preserves_source_urls():
    briefing = ResearchBriefingBuilder().build(make_result())

    assert briefing.sources == (
        "https://example.com/report",
    )


def test_briefing_is_immutable():
    briefing = ResearchBriefingBuilder().build(make_result())

    with pytest.raises(AttributeError):
        briefing.headline = "Changed."


@pytest.mark.parametrize(
    "field_name",
    [
        "business_id",
        "query",
        "headline",
    ],
)
def test_briefing_rejects_empty_required_strings(field_name):
    values = {
        "business_id": "business-001",
        "query": "Research something.",
        "headline": "Research completed.",
    }

    values[field_name] = ""

    with pytest.raises(
        (TypeError, ValueError),
        match=field_name,
    ):
        ResearchBriefing(**values)


@pytest.mark.parametrize(
    "field_name",
    [
        "findings",
        "implications",
        "options",
        "limitations",
        "sources",
    ],
)
def test_briefing_rejects_non_tuple_collections(field_name):
    values = {
        "business_id": "business-001",
        "query": "Research something.",
        "headline": "Research completed.",
        "findings": (),
        "implications": (),
        "options": (),
        "limitations": (),
        "sources": (),
    }

    values[field_name] = []

    with pytest.raises(
        TypeError,
        match=field_name,
    ):
        ResearchBriefing(**values)


@pytest.mark.parametrize(
    "field_name",
    [
        "implications",
        "options",
        "limitations",
        "sources",
    ],
)
def test_briefing_rejects_invalid_string_members(field_name):
    values = {
        "business_id": "business-001",
        "query": "Research something.",
        "headline": "Research completed.",
        "findings": (),
        "implications": (),
        "options": (),
        "limitations": (),
        "sources": (),
    }

    values[field_name] = (123,)

    with pytest.raises(
        TypeError,
        match="each",
    ):
        ResearchBriefing(**values)


def test_briefing_rejects_invalid_finding():
    with pytest.raises(
        TypeError,
        match="each finding",
    ):
        ResearchBriefing(
            business_id="business-001",
            query="Research something.",
            headline="Research completed.",
            findings=("invalid",),
        )


def test_builder_rejects_invalid_result():
    with pytest.raises(
        TypeError,
        match="ResearchResult",
    ):
        ResearchBriefingBuilder().build(object())


def test_builder_supports_empty_research_evidence():
    result = ResearchResult(
        business_id="business-001",
        query="Research something.",
        summary="Research completed.",
    )

    briefing = ResearchBriefingBuilder().build(result)

    assert briefing.findings == ()
    assert briefing.implications == ()
    assert briefing.options == ()
    assert briefing.limitations == ()
    assert briefing.sources == ()
