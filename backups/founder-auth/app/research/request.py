from dataclasses import dataclass


SUPPORTED_RESEARCH_CATEGORIES = frozenset(
    {
        "general",
        "market",
        "competitor",
        "industry",
        "product",
        "news",
        "technology",
    }
)


@dataclass(frozen=True)
class ResearchRequest:
    """Validated request for fresh external research."""

    business_id: str
    query: str
    category: str = "general"
    requester: str = "business_owner"

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError("business_id must be a non-empty string.")

        if not isinstance(self.query, str):
            raise TypeError("query must be a string.")

        if not self.query.strip():
            raise ValueError("query must be a non-empty string.")

        if not isinstance(self.category, str):
            raise TypeError("category must be a string.")

        if not self.category.strip():
            raise ValueError("category must be a non-empty string.")

        if self.category not in SUPPORTED_RESEARCH_CATEGORIES:
            raise ValueError(
                "category must be one of: "
                f"{', '.join(sorted(SUPPORTED_RESEARCH_CATEGORIES))}."
            )

        if not isinstance(self.requester, str):
            raise TypeError("requester must be a string.")

        if not self.requester.strip():
            raise ValueError("requester must be a non-empty string.")
