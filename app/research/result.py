from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchSource:
    """A validated external source used during business research."""

    title: str
    url: str
    publisher: str
    retrieved_at: str

    def __post_init__(self) -> None:
        fields = {
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "retrieved_at": self.retrieved_at,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")

            if not value.strip():
                raise ValueError(
                    f"{field_name} must be a non-empty string."
                )


@dataclass(frozen=True)
class ResearchFinding:
    """A concise evidence-backed finding produced by research."""

    statement: str
    significance: str

    def __post_init__(self) -> None:
        fields = {
            "statement": self.statement,
            "significance": self.significance,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string.")

            if not value.strip():
                raise ValueError(
                    f"{field_name} must be a non-empty string."
                )


@dataclass(frozen=True)
class ResearchResult:
    """Validated structured result returned by a research provider."""

    business_id: str
    query: str
    summary: str
    findings: tuple[ResearchFinding, ...] = ()
    sources: tuple[ResearchSource, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.business_id, str):
            raise TypeError("business_id must be a string.")

        if not self.business_id.strip():
            raise ValueError(
                "business_id must be a non-empty string."
            )

        if not isinstance(self.query, str):
            raise TypeError("query must be a string.")

        if not self.query.strip():
            raise ValueError(
                "query must be a non-empty string."
            )

        if not isinstance(self.summary, str):
            raise TypeError("summary must be a string.")

        if not self.summary.strip():
            raise ValueError(
                "summary must be a non-empty string."
            )

        if not isinstance(self.findings, tuple):
            raise TypeError("findings must be a tuple.")

        if not isinstance(self.sources, tuple):
            raise TypeError("sources must be a tuple.")

        if not isinstance(self.limitations, tuple):
            raise TypeError("limitations must be a tuple.")

        for finding in self.findings:
            if not isinstance(finding, ResearchFinding):
                raise TypeError(
                    "each finding must be a ResearchFinding."
                )

        for source in self.sources:
            if not isinstance(source, ResearchSource):
                raise TypeError(
                    "each source must be a ResearchSource."
                )

        for limitation in self.limitations:
            if not isinstance(limitation, str):
                raise TypeError(
                    "each limitation must be a string."
                )

            if not limitation.strip():
                raise ValueError(
                    "limitations cannot contain empty strings."
                )
