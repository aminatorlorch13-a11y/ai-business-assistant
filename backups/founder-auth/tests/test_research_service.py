from unittest.mock import Mock

import pytest

from app.models.business import Business
from app.research.policy import ResearchPolicy
from app.research.provider import ResearchProvider
from app.research.request import ResearchRequest
from app.research.result import (
    ResearchFinding,
    ResearchResult,
    ResearchSource,
)
from app.research.service import ResearchService


def make_business() -> Business:
    return Business(
        business_id="business-001",
        name="Example Business",
        owner_name="Business Owner",
        assistant_name="Alex",
        assistant_voice="female",
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


def make_result() -> ResearchResult:
    return ResearchResult(
        business_id="business-001",
        query="Research recent market trends.",
        summary="Several relevant market developments were identified.",
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=(),
    )


def make_provider() -> Mock:
    provider = Mock(spec=ResearchProvider)
    provider.research.return_value = make_result()
    return provider


def test_service_performs_authorized_research():
    provider = make_provider()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    request = make_request()
    result = service.research(request)

    assert result == make_result()
    provider.research.assert_called_once_with(request)


def test_service_rejects_research_when_disabled():
    provider = make_provider()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=False),
    )

    with pytest.raises(
        PermissionError,
        match="not permitted",
    ):
        service.research(make_request())

    provider.research.assert_not_called()


def test_service_rejects_request_from_another_business():
    provider = make_provider()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    request = ResearchRequest(
        business_id="business-999",
        query="Research something.",
    )

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        service.research(request)

    provider.research.assert_not_called()


def test_service_rejects_non_request():
    service = ResearchService(
        business=make_business(),
        provider=make_provider(),
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        TypeError,
        match="ResearchRequest",
    ):
        service.research(object())


def test_service_rejects_invalid_business():
    with pytest.raises(
        TypeError,
        match="business",
    ):
        ResearchService(
            business=object(),
            provider=make_provider(),
            policy=ResearchPolicy(enabled=True),
        )


def test_service_rejects_invalid_provider():
    with pytest.raises(
        TypeError,
        match="provider",
    ):
        ResearchService(
            business=make_business(),
            provider=object(),
            policy=ResearchPolicy(enabled=True),
        )


def test_service_rejects_invalid_policy():
    with pytest.raises(
        TypeError,
        match="policy",
    ):
        ResearchService(
            business=make_business(),
            provider=make_provider(),
            policy=object(),
        )


def test_service_rejects_result_for_another_business():
    provider = make_provider()

    provider.research.return_value = ResearchResult(
        business_id="business-999",
        query="Research recent market trends.",
        summary="Unauthorized result.",
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=(),
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        ValueError,
        match="result does not belong",
    ):
        service.research(make_request())


def test_service_rejects_result_for_different_query():
    provider = make_provider()

    provider.research.return_value = ResearchResult(
        business_id="business-001",
        query="Different query.",
        summary="Unexpected result.",
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=(),
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        ValueError,
        match="query does not match",
    ):
        service.research(make_request())


def test_service_rejects_invalid_provider_result():
    provider = make_provider()
    provider.research.return_value = "not a research result"

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        TypeError,
        match="ResearchResult",
    ):
        service.research(make_request())


def test_service_rejects_research_category_not_permitted():
    provider = make_provider()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset({"general"}),
        ),
    )

    request = ResearchRequest(
        business_id="business-001",
        query="Research competitors.",
        category="competitor",
    )

    with pytest.raises(
        PermissionError,
        match="not permitted",
    ):
        service.research(request)

    provider.research.assert_not_called()


def test_service_allows_permitted_research_category():
    provider = make_provider()

    request = ResearchRequest(
        business_id="business-001",
        query="Research market trends.",
        category="market",
    )

    expected_result = ResearchResult(
        business_id="business-001",
        query="Research market trends.",
        summary="Market research completed.",
        findings=(make_finding(),),
        sources=(make_source(),),
        limitations=(),
    )

    provider.research.return_value = expected_result

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset(
                {"general", "market"},
            ),
        ),
    )

    result = service.research(request)

    assert result == expected_result
    provider.research.assert_called_once_with(request)


def test_service_propagates_provider_unavailable():
    from app.research.errors import ResearchProviderUnavailable

    provider = make_provider()
    provider.research.side_effect = ResearchProviderUnavailable(
        "Research provider is unavailable."
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        ResearchProviderUnavailable,
        match="provider is unavailable",
    ):
        service.research(make_request())


def test_service_propagates_provider_timeout():
    from app.research.errors import ResearchProviderTimeout

    provider = make_provider()
    provider.research.side_effect = ResearchProviderTimeout(
        "Research provider timed out."
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        ResearchProviderTimeout,
        match="provider timed out",
    ):
        service.research(make_request())


def test_service_propagates_generic_provider_error():
    from app.research.errors import ResearchProviderError

    provider = make_provider()
    provider.research.side_effect = ResearchProviderError(
        "Research provider failed."
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
    )

    with pytest.raises(
        ResearchProviderError,
        match="Research provider failed",
    ):
        service.research(make_request())


def test_provider_is_not_called_when_request_is_unauthorized():
    provider = make_provider()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=False),
    )

    with pytest.raises(PermissionError):
        service.research(make_request())

    provider.research.assert_not_called()


def test_service_validates_provider_result_before_returning():
    from unittest.mock import Mock

    provider = make_provider()
    validator = Mock()
    validator.validate.return_value = make_result()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
        result_validator=validator,
    )

    request = make_request()
    result = service.research(request)

    validator.validate.assert_called_once_with(provider.research.return_value)
    assert result == make_result()


def test_service_propagates_result_validation_errors():
    provider = make_provider()
    validator = Mock()
    validator.validate.side_effect = ValueError(
        "findings require at least one source."
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(enabled=True),
        result_validator=validator,
    )

    with pytest.raises(
        ValueError,
        match="findings require at least one source",
    ):
        service.research(make_request())

def test_service_rejects_provider_result_with_mismatched_business_id():
    provider = make_provider()
    provider.research.return_value = ResearchResult(
        business_id="different-business",
        query="Research recent market trends.",
        summary="Several relevant developments were identified.",
        findings=(make_finding(),),
        sources=(make_source(),),
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset({"general"}),
        ),
    )

    with pytest.raises(
        ValueError,
        match="does not belong to this business",
    ):
        service.research(make_request())


def test_service_rejects_provider_result_with_mismatched_query():
    provider = make_provider()
    provider.research.return_value = ResearchResult(
        business_id="business-001",
        query="Different research query.",
        summary="Several relevant developments were identified.",
        findings=(make_finding(),),
        sources=(make_source(),),
    )

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset({"general"}),
        ),
    )

    with pytest.raises(
        ValueError,
        match="does not match the request",
    ):
        service.research(make_request())
