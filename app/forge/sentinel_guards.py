"""Strict, sequential enforcement core for Amination Forge Sentinel Guards.

This module deliberately does not define the five Guards' review responsibilities.
Those responsibilities belong to separately configured reviewer implementations.

Security boundary:
- The orchestrator obtains candidate bytes from a trusted reader.
- It computes the candidate digest itself.
- Every Guard receives the same candidate bytes and digest.
- The candidate is re-read and re-hashed after every review.
- Missing, malformed, failing, or crashing reviewers block progression.
- A PASS is accepted only from the configured reviewer implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Callable, Protocol, Sequence


GUARD_IDS = (
    "sentinel-guard-1",
    "sentinel-guard-2",
    "sentinel-guard-3",
    "sentinel-guard-4",
    "sentinel-guard-5",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSESSMENT_ISSUER_TOKEN = object()
_MAX_FINDINGS = 100
_MAX_FINDING_LENGTH = 2000


class GuardVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class AssessmentStatus(str, Enum):
    BLOCKED = "BLOCKED"
    READY_FOR_USER_ACCEPTANCE = "READY_FOR_USER_ACCEPTANCE"


@dataclass(frozen=True, slots=True)
class GuardInput:
    guard_id: str
    artifact_ref: str
    candidate_sha256: str
    candidate_bytes: bytes


@dataclass(frozen=True, slots=True)
class GuardDecision:
    verdict: GuardVerdict
    findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuardReviewer:
    guard_id: str
    implementation_id: str
    review: Callable[[GuardInput], GuardDecision]


@dataclass(frozen=True, slots=True)
class GuardResult:
    guard_id: str
    implementation_id: str | None
    artifact_ref: str
    candidate_sha256: str
    verdict: GuardVerdict
    findings: tuple[str, ...]
    reviewed_at: str


@dataclass(frozen=True, slots=True)
class SentinelAssessment:
    artifact_ref: str
    candidate_sha256: str
    status: AssessmentStatus
    results: tuple[GuardResult, ...]
    blocked_at_guard: str | None
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    @property
    def all_guards_passed(self) -> bool:
        return (
            self.status is AssessmentStatus.READY_FOR_USER_ACCEPTANCE
            and len(self.results) == len(GUARD_IDS)
            and all(r.verdict is GuardVerdict.PASS for r in self.results)
        )


def assessment_was_issued_by_service(value: object) -> bool:
    """Check in-process provenance; this is not cryptographic attestation."""
    return (
        type(value) is SentinelAssessment
        and value._issuer_token is _ASSESSMENT_ISSUER_TOKEN
    )


class CandidateChangedError(RuntimeError):
    """Raised when the candidate bytes change during a review cycle."""


class CandidateReadError(RuntimeError):
    """Raised when the trusted candidate reader fails or returns invalid data."""


class SentinelConfigurationError(ValueError):
    """Raised when reviewer configuration is structurally invalid."""


class _ReviewerProtocol(Protocol):
    guard_id: str
    implementation_id: str
    review: Callable[[GuardInput], GuardDecision]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_artifact_ref(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("artifact_ref must be a non-empty string")
    if len(value) > 512:
        raise ValueError("artifact_ref is too long")


def _read_candidate(reader: Callable[[], bytes]) -> tuple[bytes, str]:
    try:
        candidate = reader()
    except Exception as exc:
        raise CandidateReadError("Trusted candidate read failed") from exc

    if not isinstance(candidate, bytes):
        raise CandidateReadError("Trusted candidate reader must return bytes")
    if not candidate:
        raise CandidateReadError("Candidate artifact is empty")

    digest = hashlib.sha256(candidate).hexdigest()
    if not _SHA256_RE.fullmatch(digest):
        raise CandidateReadError("Candidate digest calculation failed")

    return candidate, digest


def _validate_reviewers(
    reviewers: Sequence[_ReviewerProtocol | None],
) -> tuple[_ReviewerProtocol | None, ...]:
    if isinstance(reviewers, (str, bytes)):
        raise SentinelConfigurationError("Reviewers must be a sequence")

    configured = tuple(reviewers)
    if len(configured) != len(GUARD_IDS):
        raise SentinelConfigurationError(
            "Exactly five reviewer slots are required"
        )

    for expected_id, reviewer in zip(GUARD_IDS, configured):
        if reviewer is None:
            continue

        if getattr(reviewer, "guard_id", None) != expected_id:
            raise SentinelConfigurationError(
                f"Reviewer slot must be configured for {expected_id}"
            )

        implementation_id = getattr(reviewer, "implementation_id", None)
        if (
            not isinstance(implementation_id, str)
            or not implementation_id.strip()
            or len(implementation_id) > 200
        ):
            raise SentinelConfigurationError(
                f"{expected_id} has an invalid implementation_id"
            )

        if not callable(getattr(reviewer, "review", None)):
            raise SentinelConfigurationError(
                f"{expected_id} has no callable review implementation"
            )

    return configured


def _normalise_decision(value: object) -> GuardDecision:
    # Require the exact contract type. Do not accept arbitrary dictionaries,
    # truthy values, strings, booleans, or caller-supplied approval objects.
    if type(value) is not GuardDecision:
        raise TypeError("Reviewer returned a malformed decision")

    if type(value.verdict) is not GuardVerdict:
        raise TypeError("Reviewer returned an invalid verdict")

    if type(value.findings) is not tuple:
        raise TypeError("Reviewer findings must be a tuple")

    if len(value.findings) > _MAX_FINDINGS:
        raise ValueError("Reviewer returned too many findings")

    for finding in value.findings:
        if (
            not isinstance(finding, str)
            or not finding.strip()
            or len(finding) > _MAX_FINDING_LENGTH
        ):
            raise ValueError("Reviewer returned an invalid finding")

    return value


class ForgeSentinelAssessmentService:
    """Runs the five configured Sentinel reviewers in strict fixed order.

    This is the enforcement core, not the durable assessment store or the
    production worker/terminal integration. Those must use this same service.
    """

    def __init__(
        self,
        reviewers: Sequence[_ReviewerProtocol | None],
    ) -> None:
        self._reviewers = _validate_reviewers(reviewers)

    def assess(
        self,
        *,
        artifact_ref: str,
        candidate_reader: Callable[[], bytes],
    ) -> SentinelAssessment:
        _validate_artifact_ref(artifact_ref)

        if not callable(candidate_reader):
            raise TypeError("candidate_reader must be callable")

        candidate, digest = _read_candidate(candidate_reader)
        results: list[GuardResult] = []

        for guard_id, reviewer in zip(GUARD_IDS, self._reviewers):
            # Verify the source artifact before every Guard. This also
            # catches a stale or replaced artifact between sequential reviews.
            current_candidate, current_digest = _read_candidate(candidate_reader)
            if current_digest != digest or current_candidate != candidate:
                raise CandidateChangedError(
                    "Candidate changed during Sentinel review; all approvals "
                    "for this review cycle are invalid"
                )

            if reviewer is None:
                decision = GuardDecision(
                    GuardVerdict.INCONCLUSIVE,
                    ("Reviewer is not configured; approval is prohibited.",),
                )
                implementation_id = None
            else:
                implementation_id = reviewer.implementation_id
                review_input = GuardInput(
                    guard_id=guard_id,
                    artifact_ref=artifact_ref,
                    candidate_sha256=digest,
                    candidate_bytes=candidate,
                )

                try:
                    raw_decision = reviewer.review(review_input)
                    decision = _normalise_decision(raw_decision)
                except Exception as exc:
                    # Do not expose exception internals as trusted findings.
                    decision = GuardDecision(
                        GuardVerdict.INCONCLUSIVE,
                        (
                            "Reviewer execution or result validation failed: "
                            f"{type(exc).__name__}",
                        ),
                    )

            # A reviewer must not be able to alter the candidate and then
            # have its result accepted for the old digest.
            after_candidate, after_digest = _read_candidate(candidate_reader)
            if after_digest != digest or after_candidate != candidate:
                raise CandidateChangedError(
                    "Candidate changed during Sentinel review; all approvals "
                    "for this review cycle are invalid"
                )

            result = GuardResult(
                guard_id=guard_id,
                implementation_id=implementation_id,
                artifact_ref=artifact_ref,
                candidate_sha256=digest,
                verdict=decision.verdict,
                findings=decision.findings,
                reviewed_at=_utc_now(),
            )
            results.append(result)

            # Only PASS advances. FAIL and INCONCLUSIVE both halt the cycle.
            if decision.verdict is not GuardVerdict.PASS:
                return SentinelAssessment(
                    artifact_ref=artifact_ref,
                    candidate_sha256=digest,
                    status=AssessmentStatus.BLOCKED,
                    results=tuple(results),
                    blocked_at_guard=guard_id,
                    _issuer_token=_ASSESSMENT_ISSUER_TOKEN,
                )

        # This means only that all five configured reviewers passed.
        # It does NOT authorize release or deployment.
        return SentinelAssessment(
            artifact_ref=artifact_ref,
            candidate_sha256=digest,
            status=AssessmentStatus.READY_FOR_USER_ACCEPTANCE,
            results=tuple(results),
            blocked_at_guard=None,
            _issuer_token=_ASSESSMENT_ISSUER_TOKEN,
        )
