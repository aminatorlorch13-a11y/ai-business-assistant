from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from app.forge.engineering_standard import ForgeStage, REQUIRED_GATE_EVIDENCE


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EvidenceOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_RUN = "not_run"


class EvidenceOrigin(str, Enum):
    AUTOMATED_TOOL = "automated_tool"
    RUNTIME_OBSERVATION = "runtime_observation"
    HUMAN_REVIEW = "human_review"
    EXTERNAL_EXPERT = "external_expert"
    USER_ACCEPTANCE = "user_acceptance"


_AUTOMATED_REQUIREMENTS = frozenset({
    "build_verified",
    "unit_tests",
    "integration_tests",
    "regression_tests",
    "runtime_smoke_tests",
})

_REQUIRED_ORIGINS = {
    "legal_risk_review": EvidenceOrigin.EXTERNAL_EXPERT,
    "user_acceptance": EvidenceOrigin.USER_ACCEPTANCE,
}


@dataclass(frozen=True)
class ForgeEvidence:
    """A provenance-bearing record supporting one engineering gate decision."""

    evidence_id: str
    stage: ForgeStage
    requirement: str
    outcome: EvidenceOutcome
    origin: EvidenceOrigin
    artifact_ref: str
    artifact_sha256: str
    verifier_id: str
    verified_at: datetime
    tool_name: str | None = None
    tool_version: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "artifact_ref",
            "verifier_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
            if len(value) > 512:
                raise ValueError(f"{name} exceeds the maximum length.")

        if not isinstance(self.stage, ForgeStage):
            raise TypeError("stage must be a ForgeStage.")
        if not isinstance(self.outcome, EvidenceOutcome):
            raise TypeError("outcome must be an EvidenceOutcome.")
        if not isinstance(self.origin, EvidenceOrigin):
            raise TypeError("origin must be an EvidenceOrigin.")

        if self.requirement not in REQUIRED_GATE_EVIDENCE[self.stage]:
            raise ValueError("Unknown requirement for the selected stage.")

        if not isinstance(self.artifact_sha256, str) or not _SHA256_PATTERN.fullmatch(
            self.artifact_sha256
        ):
            raise ValueError("artifact_sha256 must be a lowercase SHA-256 digest.")

        if not isinstance(self.verified_at, datetime):
            raise TypeError("verified_at must be a datetime.")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware.")

        if not isinstance(self.notes, str) or len(self.notes) > 2048:
            raise ValueError("notes must be a string of at most 2048 characters.")

        if self.requirement in _AUTOMATED_REQUIREMENTS:
            if self.origin not in {
                EvidenceOrigin.AUTOMATED_TOOL,
                EvidenceOrigin.RUNTIME_OBSERVATION,
            }:
                raise ValueError(
                    "This requirement needs automated or runtime evidence."
                )

        required_origin = _REQUIRED_ORIGINS.get(self.requirement)
        if required_origin is not None and self.origin != required_origin:
            raise ValueError(
                f"{self.requirement} requires {required_origin.value} evidence."
            )

        if self.origin == EvidenceOrigin.AUTOMATED_TOOL:
            for name in ("tool_name", "tool_version"):
                value = getattr(self, name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{name} is required for automated-tool evidence."
                    )
                if len(value) > 128:
                    raise ValueError(f"{name} exceeds the maximum length.")


def missing_evidence_records(
    stage: ForgeStage,
    records: Iterable[ForgeEvidence],
) -> tuple[str, ...]:
    """Return mandatory checks without exactly one passing evidence record."""
    if not isinstance(stage, ForgeStage):
        raise TypeError("stage must be a ForgeStage.")

    if isinstance(records, (str, bytes)):
        raise TypeError("records must be an iterable of ForgeEvidence.")

    try:
        items = tuple(records)
    except TypeError as exc:
        raise TypeError("records must be iterable.") from exc

    by_requirement: dict[str, ForgeEvidence] = {}

    for record in items:
        if not isinstance(record, ForgeEvidence):
            raise TypeError("Every evidence item must be ForgeEvidence.")
        if record.stage != stage:
            raise ValueError("Evidence belongs to a different stage.")
        if record.requirement in by_requirement:
            raise ValueError(
                f"Duplicate evidence for requirement: {record.requirement}."
            )
        by_requirement[record.requirement] = record

    required = REQUIRED_GATE_EVIDENCE[stage]
    return tuple(sorted(
        requirement
        for requirement in required
        if (
            requirement not in by_requirement
            or by_requirement[requirement].outcome != EvidenceOutcome.PASS
        )
    ))


def validate_evidence_gate(
    stage: ForgeStage,
    records: Iterable[ForgeEvidence],
) -> None:
    missing = missing_evidence_records(stage, records)
    if missing:
        raise ValueError(
            "Evidence gate is not satisfied: " + ", ".join(missing)
        )
