from datetime import datetime, timezone

import pytest

from app.forge.engineering_standard import ForgeStage, REQUIRED_GATE_EVIDENCE
from app.forge.evidence import (
    EvidenceOrigin,
    EvidenceOutcome,
    ForgeEvidence,
    missing_evidence_records,
    validate_evidence_gate,
)

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def make_evidence(
    requirement,
    *,
    stage=ForgeStage.DISCOVERY,
    outcome=EvidenceOutcome.PASS,
    origin=EvidenceOrigin.HUMAN_REVIEW,
    **kwargs,
):
    values = {
        "evidence_id": f"ev-{requirement}",
        "stage": stage,
        "requirement": requirement,
        "outcome": outcome,
        "origin": origin,
        "artifact_ref": f"artifact://{requirement}",
        "artifact_sha256": DIGEST,
        "verifier_id": "reviewer-1",
        "verified_at": NOW,
    }
    values.update(kwargs)
    return ForgeEvidence(**values)


def test_evidence_requires_valid_artifact_digest():
    with pytest.raises(ValueError, match="SHA-256"):
        ForgeEvidence(
            evidence_id="ev-1",
            stage=ForgeStage.DISCOVERY,
            requirement="user_goal_confirmed",
            outcome=EvidenceOutcome.PASS,
            origin=EvidenceOrigin.HUMAN_REVIEW,
            artifact_ref="artifact://requirements",
            artifact_sha256="not-a-digest",
            verifier_id="reviewer-1",
            verified_at=NOW,
        )


def test_evidence_requires_timezone_aware_verification_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_evidence(
            "user_goal_confirmed",
            verified_at=datetime(2026, 11, 3, 8, 0),
        )


def test_unknown_requirement_is_rejected():
    with pytest.raises(ValueError, match="Unknown requirement"):
        make_evidence("imaginary_check")


@pytest.mark.parametrize(
    "outcome",
    [
        EvidenceOutcome.FAIL,
        EvidenceOutcome.INCONCLUSIVE,
        EvidenceOutcome.NOT_RUN,
    ],
)
def test_non_passing_evidence_does_not_satisfy_gate(outcome):
    records = [
        make_evidence("user_goal_confirmed", outcome=outcome),
        make_evidence("existing_system_inspected"),
        make_evidence("constraints_recorded"),
    ]
    assert missing_evidence_records(ForgeStage.DISCOVERY, records) == (
        "user_goal_confirmed",
    )


def test_all_passing_evidence_satisfies_gate():
    records = [
        make_evidence(requirement)
        for requirement in REQUIRED_GATE_EVIDENCE[ForgeStage.DISCOVERY]
    ]
    validate_evidence_gate(ForgeStage.DISCOVERY, records)


def test_missing_evidence_blocks_gate():
    records = [make_evidence("user_goal_confirmed")]
    with pytest.raises(ValueError, match="Evidence gate is not satisfied"):
        validate_evidence_gate(ForgeStage.DISCOVERY, records)


def test_duplicate_evidence_is_rejected():
    record = make_evidence("user_goal_confirmed")
    with pytest.raises(ValueError, match="Duplicate evidence"):
        missing_evidence_records(ForgeStage.DISCOVERY, [record, record])


def test_evidence_from_another_stage_is_rejected():
    record = make_evidence("user_goal_confirmed")
    with pytest.raises(ValueError, match="different stage"):
        missing_evidence_records(ForgeStage.REQUIREMENTS, [record])


def test_automated_evidence_requires_tool_identity_and_version():
    with pytest.raises(ValueError, match="tool_name"):
        make_evidence(
            "unit_tests",
            stage=ForgeStage.SELF_VERIFICATION,
            origin=EvidenceOrigin.AUTOMATED_TOOL,
        )


def test_legal_review_requires_external_expert_evidence():
    with pytest.raises(ValueError, match="external_expert"):
        make_evidence(
            "legal_risk_review",
            stage=ForgeStage.INDEPENDENT_REVIEW,
            origin=EvidenceOrigin.HUMAN_REVIEW,
        )


def test_user_acceptance_requires_user_acceptance_evidence():
    with pytest.raises(ValueError, match="user_acceptance"):
        make_evidence(
            "user_acceptance",
            stage=ForgeStage.USER_ACCEPTANCE,
            origin=EvidenceOrigin.HUMAN_REVIEW,
        )
