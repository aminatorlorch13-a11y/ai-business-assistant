from unittest.mock import Mock

import pytest

from app.models.business import Business
from app.research.briefing import (
    ResearchBriefingBuilder,
)
from app.research.orchestrator import ResearchOrchestrator
from app.research.policy import ResearchPolicy
from app.research.provider import ResearchProvider
from app.research.request import ResearchRequest
from app.research.result_validator import ResearchResultValidator
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


def make_request() -> ResearchRequest:
    return ResearchRequest(
        business_id="business-001",
        query="Research recent market trends.",
        category="market",
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


def make_service() -> Mock:
    service = Mock(spec=ResearchService)
    service.research.return_value = make_result()
    return service


def make_orchestrator(
    service: Mock | None = None,
) -> ResearchOrchestrator:
    if service is None:
        service = make_service()

    return ResearchOrchestrator(
        service=service,
        briefing_builder=ResearchBriefingBuilder(),
        result_validator=ResearchResultValidator(),
    )


def test_orchestrator_performs_research():
    service = make_service()
    orchestrator = make_orchestrator(service)

    request = make_request()

    briefing = orchestrator.research(request)

    service.research.assert_called_once_with(request)
    assert briefing.business_id == "business-001"
    assert briefing.query == request.query


def test_orchestrator_returns_owner_briefing():
    orchestrator = make_orchestrator()

    briefing = orchestrator.research(make_request())

    assert briefing.headline == (
        "Several relevant developments were identified."
    )
    assert briefing.findings == (make_finding(),)
    assert briefing.implications == (
        "This may indicate a growth opportunity.",
    )


def test_orchestrator_preserves_sources():
    orchestrator = make_orchestrator()

    briefing = orchestrator.research(make_request())

    assert briefing.sources == (
        "https://example.com/report",
    )


def test_orchestrator_preserves_limitations():
    orchestrator = make_orchestrator()

    briefing = orchestrator.research(make_request())

    assert briefing.limitations == (
        "Some market data may lag.",
    )


def test_orchestrator_rejects_non_request():
    orchestrator = make_orchestrator()

    with pytest.raises(
        TypeError,
        match="ResearchRequest",
    ):
        orchestrator.research(object())


def test_orchestrator_rejects_invalid_service():
    with pytest.raises(
        TypeError,
        match="service",
    ):
        ResearchOrchestrator(
            service=object(),
            briefing_builder=ResearchBriefingBuilder(),
            result_validator=ResearchResultValidator(),
        )


def test_orchestrator_rejects_invalid_briefing_builder():
    service = make_service()

    with pytest.raises(
        TypeError,
        match="briefing_builder",
    ):
        ResearchOrchestrator(
            service=service,
            briefing_builder=object(),
            result_validator=ResearchResultValidator(),
        )


def test_orchestrator_does_not_bypass_service():
    service = make_service()
    orchestrator = make_orchestrator(service)

    request = make_request()

    orchestrator.research(request)

    service.research.assert_called_once_with(request)


def test_orchestrator_propagates_service_permission_errors():
    service = make_service()
    service.research.side_effect = PermissionError(
        "External research is not permitted."
    )

    orchestrator = make_orchestrator(service)

    with pytest.raises(
        PermissionError,
        match="not permitted",
    ):
        orchestrator.research(make_request())


def test_orchestrator_propagates_service_business_boundary_errors():
    service = make_service()
    service.research.side_effect = ValueError(
        "Research request does not belong to this business."
    )

    orchestrator = make_orchestrator(service)

    with pytest.raises(
        ValueError,
        match="does not belong",
    ):
        orchestrator.research(make_request())


def test_orchestrator_rejects_invalid_service_result():
    service = make_service()
    service.research.return_value = "invalid result"

    orchestrator = make_orchestrator(service)

    with pytest.raises(
        TypeError,
        match="ResearchResult",
    ):
        orchestrator.research(make_request())


def test_orchestrator_accepts_real_research_service():
    provider = Mock(spec=ResearchProvider)
    provider.research.return_value = make_result()

    service = ResearchService(
        business=make_business(),
        provider=provider,
        policy=ResearchPolicy(
            enabled=True,
            allowed_categories=frozenset({"market"}),
        ),
    )

    orchestrator = ResearchOrchestrator(
        service=service,
        briefing_builder=ResearchBriefingBuilder(),
        result_validator=ResearchResultValidator(),
    )

    briefing = orchestrator.research(make_request())

    assert briefing.business_id == "business-001"
    assert briefing.query == "Research recent market trends."
    provider.research.assert_called_once_with(
        make_request()
    )


def test_orchestrator_validates_result_before_building_briefing():
    service = make_service()

    validator = Mock(spec=ResearchResultValidator)
    validator.validate.return_value = make_result()

    orchestrator = ResearchOrchestrator(
        service=service,
        briefing_builder=ResearchBriefingBuilder(),
        result_validator=validator,
    )

    request = make_request()

    briefing = orchestrator.research(request)

    validator.validate.assert_called_once_with(
        service.research.return_value
    )
    assert briefing.business_id == "business-001"


def test_orchestrator_propagates_validator_errors():
    service = make_service()

    validator = Mock(spec=ResearchResultValidator)
    validator.validate.side_effect = ValueError(
        "research result failed validation."
    )

    orchestrator = ResearchOrchestrator(
        service=service,
        briefing_builder=ResearchBriefingBuilder(),
        result_validator=validator,
    )

    with pytest.raises(
        ValueError,
        match="failed validation",
    ):
        orchestrator.research(make_request())


def test_orchestrator_rejects_invalid_result_validator():
    service = make_service()

    with pytest.raises(
        TypeError,
        match="result_validator",
    ):
        ResearchOrchestrator(
            service=service,
            briefing_builder=ResearchBriefingBuilder(),
            result_validator=object(),
        )
