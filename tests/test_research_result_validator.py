import pytest

from app.research.result import (
    ResearchFinding,
    ResearchResult,
    ResearchSource,
)
from app.research.result_validator import ResearchResultValidator


def make_source(
    url: str = "https://example.com/report",
) -> ResearchSource:
    return ResearchSource(
        title="Market Report",
        url=url,
        publisher="Example Publisher",
        retrieved_at="2026-09-01T10:00:00+02:00",
    )


def make_finding(
    statement: str = "Demand increased.",
) -> ResearchFinding:
    return ResearchFinding(
        statement=statement,
        significance="This may indicate growth.",
    )


def make_result(
    *,
    findings=(
        ResearchFinding(
            statement="Demand increased.",
            significance="This may indicate growth.",
        ),
    ),
    sources=(
        ResearchSource(
            title="Market Report",
            url="https://example.com/report",
            publisher="Example Publisher",
            retrieved_at="2026-09-01T10:00:00+02:00",
        ),
    ),
    limitations=("Some data may lag.",),
) -> ResearchResult:
    return ResearchResult(
        business_id="business-001",
        query="Research recent market trends.",
        summary="Several relevant developments were identified.",
        findings=findings,
        sources=sources,
        limitations=limitations,
    )


def test_validator_accepts_valid_result():
    result = make_result()

    validated = ResearchResultValidator().validate(result)

    assert validated is result


def test_validator_rejects_non_result():
    with pytest.raises(
        TypeError,
        match="ResearchResult",
    ):
        ResearchResultValidator().validate(object())


def test_validator_preserves_result_identity():
    result = make_result()

    validated = ResearchResultValidator().validate(result)

    assert validated is result


def test_validator_rejects_findings_without_sources():
    result = make_result(
        findings=(make_finding(),),
        sources=(),
    )

    with pytest.raises(
        ValueError,
        match="findings require at least one source",
    ):
        ResearchResultValidator().validate(result)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/report",
        "file:///tmp/report",
        "example.com/report",
        "://invalid",
    ],
)
def test_validator_rejects_non_http_source_urls(url):
    result = make_result(
        sources=(make_source(url),),
    )

    with pytest.raises(
        ValueError,
        match="HTTP",
    ):
        ResearchResultValidator().validate(result)


def test_validator_rejects_duplicate_source_urls():
    source = make_source()

    result = make_result(
        sources=(source, source),
    )

    with pytest.raises(
        ValueError,
        match="duplicate source URL",
    ):
        ResearchResultValidator().validate(result)


def test_validator_allows_multiple_distinct_sources():
    result = make_result(
        sources=(
            make_source("https://example.com/one"),
            make_source("https://example.com/two"),
        ),
    )

    validated = ResearchResultValidator().validate(result)

    assert validated is result


def test_validator_allows_result_without_findings():
    result = make_result(
        findings=(),
        sources=(),
    )

    validated = ResearchResultValidator().validate(result)

    assert validated is result


def test_validator_preserves_all_result_fields():
    result = make_result()

    validated = ResearchResultValidator().validate(result)

    assert validated.business_id == result.business_id
    assert validated.query == result.query
    assert validated.summary == result.summary
    assert validated.findings == result.findings
    assert validated.sources == result.sources
    assert validated.limitations == result.limitations


def test_validator_rejects_duplicate_source_urls_with_different_trailing_slashes():
    result = make_result(
        sources=(
            make_source("https://example.com/report"),
            make_source("https://example.com/report/"),
        ),
    )

    with pytest.raises(
        ValueError,
        match="duplicate source URL",
    ):
        ResearchResultValidator().validate(result)


def test_validator_rejects_source_without_hostname():
    result = make_result(
        sources=(make_source("https:///missing-host"),),
    )

    with pytest.raises(
        ValueError,
        match="HTTP",
    ):
        ResearchResultValidator().validate(result)


@pytest.mark.parametrize(
    "url",
    [
        "http://",
        "https://",
        "https:///path",
    ],
)
def test_validator_rejects_malformed_http_urls(url):
    result = make_result(
        sources=(make_source(url),),
    )

    with pytest.raises(
        ValueError,
        match="HTTP",
    ):
        ResearchResultValidator().validate(result)
