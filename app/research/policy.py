from dataclasses import dataclass, field

from app.research.request import (
    SUPPORTED_RESEARCH_CATEGORIES,
    ResearchRequest,
)


@dataclass(frozen=True)
class ResearchPolicy:
    """Controls whether and what kind of external research is permitted."""

    enabled: bool = False
    allowed_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"general"})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean.")

        if not isinstance(self.allowed_categories, frozenset):
            raise TypeError("allowed_categories must be a frozenset.")

        unknown_categories = (
            self.allowed_categories - SUPPORTED_RESEARCH_CATEGORIES
        )

        if unknown_categories:
            raise ValueError(
                "allowed_categories contains unsupported categories: "
                f"{', '.join(sorted(unknown_categories))}."
            )

    def allows(self, request: ResearchRequest) -> bool:
        """Return whether the supplied research request is permitted."""

        if not isinstance(request, ResearchRequest):
            raise TypeError("request must be a ResearchRequest.")

        if not self.enabled:
            return False

        return request.category in self.allowed_categories
