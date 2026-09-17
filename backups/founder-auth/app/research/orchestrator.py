from app.research.briefing import (
    ResearchBriefing,
    ResearchBriefingBuilder,
)
from app.research.request import ResearchRequest
from app.research.result import ResearchResult
from app.research.result_validator import ResearchResultValidator
from app.research.service import ResearchService


class ResearchOrchestrator:
    """Coordinates authorized research and converts validated evidence into a briefing."""

    def __init__(
        self,
        service: ResearchService,
        briefing_builder: ResearchBriefingBuilder,
        result_validator: ResearchResultValidator,
    ) -> None:
        if not isinstance(service, ResearchService):
            raise TypeError(
                "service must be a ResearchService."
            )

        if not isinstance(
            briefing_builder,
            ResearchBriefingBuilder,
        ):
            raise TypeError(
                "briefing_builder must be a ResearchBriefingBuilder."
            )

        if not isinstance(
            result_validator,
            ResearchResultValidator,
        ):
            raise TypeError(
                "result_validator must be a ResearchResultValidator."
            )

        self._service = service
        self._briefing_builder = briefing_builder
        self._result_validator = result_validator

    def research(
        self,
        request: ResearchRequest,
    ) -> ResearchBriefing:
        """Perform authorized research and produce an owner briefing."""

        if not isinstance(request, ResearchRequest):
            raise TypeError(
                "request must be a ResearchRequest."
            )

        result = self._service.research(request)

        if not isinstance(result, ResearchResult):
            raise TypeError(
                "research service must return a ResearchResult."
            )

        validated_result = self._result_validator.validate(
            result
        )

        return self._briefing_builder.build(
            validated_result
        )
