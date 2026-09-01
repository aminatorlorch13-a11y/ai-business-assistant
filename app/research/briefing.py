from dataclasses import dataclass

from app.research.result import ResearchFinding, ResearchResult


@dataclass(frozen=True)
class ResearchBriefing:
    """Owner-facing decision-support briefing produced from research evidence."""

    business_id: str
    query: str
    headline: str
    findings: tuple[ResearchFinding, ...] = ()
    implications: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

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

        if not isinstance(self.headline, str):
            raise TypeError("headline must be a string.")

        if not self.headline.strip():
            raise ValueError(
                "headline must be a non-empty string."
            )

        if not isinstance(self.findings, tuple):
            raise TypeError("findings must be a tuple.")

        if not isinstance(self.implications, tuple):
            raise TypeError("implications must be a tuple.")

        if not isinstance(self.options, tuple):
            raise TypeError("options must be a tuple.")

        if not isinstance(self.limitations, tuple):
            raise TypeError("limitations must be a tuple.")

        if not isinstance(self.sources, tuple):
            raise TypeError("sources must be a tuple.")

        for finding in self.findings:
            if not isinstance(finding, ResearchFinding):
                raise TypeError(
                    "each finding must be a ResearchFinding."
                )

        for implication in self.implications:
            if not isinstance(implication, str):
                raise TypeError(
                    "each implication must be a string."
                )

            if not implication.strip():
                raise ValueError(
                    "implications cannot contain empty strings."
                )

        for option in self.options:
            if not isinstance(option, str):
                raise TypeError(
                    "each option must be a string."
                )

            if not option.strip():
                raise ValueError(
                    "options cannot contain empty strings."
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

        for source in self.sources:
            if not isinstance(source, str):
                raise TypeError(
                    "each source must be a string."
                )

            if not source.strip():
                raise ValueError(
                    "sources cannot contain empty strings."
                )


class ResearchBriefingBuilder:
    """Builds a safe owner-facing briefing from validated research."""

    def build(self, result: ResearchResult) -> ResearchBriefing:
        if not isinstance(result, ResearchResult):
            raise TypeError(
                "result must be a ResearchResult."
            )

        headline = result.summary.strip()

        implications = tuple(
            finding.significance.strip()
            for finding in result.findings
        )

        options = tuple(
            self._build_option(finding)
            for finding in result.findings
        )

        sources = tuple(
            source.url
            for source in result.sources
        )

        return ResearchBriefing(
            business_id=result.business_id,
            query=result.query,
            headline=headline,
            findings=result.findings,
            implications=implications,
            options=options,
            limitations=result.limitations,
            sources=sources,
        )

    @staticmethod
    def _build_option(finding: ResearchFinding) -> str:
        return (
            "Consider investigating or testing the opportunity described by "
            f"this finding: {finding.statement.strip()}"
        )
