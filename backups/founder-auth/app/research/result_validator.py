from urllib.parse import urlparse

from app.research.result import ResearchResult


class ResearchResultValidator:
    """Validates research results before they enter downstream processing."""

    def validate(self, result: ResearchResult) -> ResearchResult:
        if not isinstance(result, ResearchResult):
            raise TypeError("result must be a ResearchResult.")

        if not result.business_id.strip():
            raise ValueError("result business_id must be non-empty.")

        if not result.query.strip():
            raise ValueError("result query must be non-empty.")

        if not result.summary.strip():
            raise ValueError("result summary must be non-empty.")

        if result.findings and not result.sources:
            raise ValueError(
                "findings require at least one source."
            )

        self._validate_sources(result)

        return result

    @staticmethod
    def _validate_sources(result: ResearchResult) -> None:
        seen_urls: set[str] = set()

        for source in result.sources:
            parsed = urlparse(source.url)

            if parsed.scheme not in {"http", "https"}:
                raise ValueError(
                    "source URL must use HTTP or HTTPS."
                )

            if not parsed.netloc:
                raise ValueError(
                    "source URL must use HTTP or HTTPS."
                )

            normalized_url = source.url.rstrip("/")

            if normalized_url in seen_urls:
                raise ValueError(
                    "duplicate source URL."
                )

            seen_urls.add(normalized_url)
