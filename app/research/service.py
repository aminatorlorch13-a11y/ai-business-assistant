from app.models.business import Business
from app.research.policy import ResearchPolicy
from app.research.provider import ResearchProvider
from app.research.request import ResearchRequest
from app.research.result import ResearchResult
from app.research.result_validator import ResearchResultValidator


class ResearchService:
    """Coordinates authorized external research for a business."""

    def __init__(
        self,
        business: Business,
        provider: ResearchProvider,
        policy: ResearchPolicy,
        result_validator: ResearchResultValidator | None = None,
    ) -> None:
        if not isinstance(business, Business):
            raise TypeError("business must be a Business.")

        if not isinstance(provider, ResearchProvider):
            raise TypeError("provider must be a ResearchProvider.")

        if not isinstance(policy, ResearchPolicy):
            raise TypeError("policy must be a ResearchPolicy.")

        if result_validator is None:
            result_validator = ResearchResultValidator()

        if not callable(getattr(result_validator, "validate", None)):
            raise TypeError(
                "result_validator must provide a callable validate method."
            )

        self._business = business
        self._provider = provider
        self._policy = policy
        self._result_validator = result_validator

    def research(self, request: ResearchRequest) -> ResearchResult:
        """Perform research only after business and policy boundaries pass."""

        if not isinstance(request, ResearchRequest):
            raise TypeError("request must be a ResearchRequest.")

        if request.business_id != self._business.business_id:
            raise ValueError(
                "Research request does not belong to this business."
            )

        if not self._policy.allows(request):
            raise PermissionError(
                "External research is not permitted."
            )

        result = self._provider.research(request)

        if not isinstance(result, ResearchResult):
            raise TypeError(
                "Research provider must return a ResearchResult."
            )

        if result.business_id != self._business.business_id:
            raise ValueError(
                "Research result does not belong to this business."
            )

        if result.query != request.query:
            raise ValueError(
                "Research result query does not match the request."
            )

        return self._result_validator.validate(result)
