"""Focused tests for Forge user acceptance evidence and validation."""

from datetime import datetime, timezone

import pytest

from app.forge.acceptance_service import (
    ForgeAcceptanceService,
    ForgeAcceptanceServiceError,
)
from app.forge.acceptance_store import ForgeAcceptanceDecision
from app.forge.evidence import (
    EvidenceOutcome,
    missing_evidence_records,
    validate_evidence_gate,
)
from app.forge.engineering_standard import ForgeStage


def make_decision(
    *,
    decision="accepted",
    live_test_confirmed=True,
    limitations_disclosed=True,
):
    return ForgeAcceptanceDecision(
        decision_id="decision-123",
        business_id="business-1",
        project_id="project-1",
        job_id="job-1",
        artifact_ref="forge-artifact://" + ("a" * 32),
        candidate_sha256="b" * 64,
        sentinel_assessment_id="assessment-123",
        actor_user_id="founder-1",
        decision=decision,
        live_test_confirmed=live_test_confirmed,
        limitations_disclosed=limitations_disclosed,
        feedback="Please improve the loading experience."
        if decision == "changes_requested" else "",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_accepted_decision_reconstructs_complete_passing_gate_evidence():
    decision = make_decision()

    records = ForgeAcceptanceService.evidence_for_decision(decision)

    assert len(records) == 3
    assert {item.requirement for item in records} == {
        "user_live_test",
        "limitations_disclosed",
        "user_acceptance",
    }
    assert all(item.outcome is EvidenceOutcome.PASS for item in records)
    assert all(item.artifact_sha256 == decision.candidate_sha256 for item in records)
    assert all(item.artifact_ref == decision.artifact_ref for item in records)
    assert all(item.verifier_id == decision.actor_user_id for item in records)
    assert all(item.evidence_id.startswith(decision.decision_id + ":") for item in records)

    validate_evidence_gate(ForgeStage.USER_ACCEPTANCE, records)


def test_changes_requested_never_passes_user_acceptance_gate():
    decision = make_decision(
        decision="changes_requested",
        live_test_confirmed=True,
        limitations_disclosed=True,
    )

    records = ForgeAcceptanceService.evidence_for_decision(decision)

    assert len(records) == 3
    acceptance = next(
        item for item in records
        if item.requirement == "user_acceptance"
    )
    assert acceptance.outcome is EvidenceOutcome.FAIL
    assert missing_evidence_records(ForgeStage.USER_ACCEPTANCE, records) == (
        "user_acceptance",
    )


def test_unconfirmed_items_are_inconclusive_not_passed():
    decision = make_decision(
        decision="changes_requested",
        live_test_confirmed=False,
        limitations_disclosed=False,
    )

    records = ForgeAcceptanceService.evidence_for_decision(decision)
    outcomes = {item.requirement: item.outcome for item in records}

    assert outcomes["user_live_test"] is EvidenceOutcome.INCONCLUSIVE
    assert outcomes["limitations_disclosed"] is EvidenceOutcome.INCONCLUSIVE
    assert outcomes["user_acceptance"] is EvidenceOutcome.FAIL
    assert len(missing_evidence_records(ForgeStage.USER_ACCEPTANCE, records)) == 3


def test_evidence_reconstruction_rejects_naive_timestamp():
    decision = make_decision()
    decision = ForgeAcceptanceDecision(
        **{
            **decision.__dict__,
            "created_at": "2026-11-09T10:00:00",
        }
    )

    with pytest.raises(ForgeAcceptanceServiceError):
        ForgeAcceptanceService.evidence_for_decision(decision)


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"decision": "release"}, ValueError),
        ({"decision": "accepted", "live_test_confirmed": False}, ValueError),
        ({"decision": "accepted", "limitations_disclosed": False}, ValueError),
        ({"decision": "changes_requested", "feedback": "   "}, ValueError),
        ({"decision": "changes_requested", "feedback": "x" * 4097}, ValueError),
        ({"decision": "accepted", "live_test_confirmed": 1}, TypeError),
        ({"decision": "accepted", "limitations_disclosed": 1}, TypeError),
        ({"decision": "accepted", "actor_user_id": " founder-1 "}, ValueError),
    ],
)
def test_invalid_input_is_rejected_before_candidate_or_sentinel_access(
    kwargs, error
):
    service = object.__new__(ForgeAcceptanceService)

    class MustNotBeCalled:
        def __getattr__(self, name):
            raise AssertionError(
                f"Unexpected dependency access before validation: {name}"
            )

    service._store = MustNotBeCalled()
    service._sentinel_coordinator = MustNotBeCalled()

    values = {
        "actor_user_id": "founder-1",
        "decision": "accepted",
        "live_test_confirmed": True,
        "limitations_disclosed": True,
        "feedback": "",
    }
    values.update(kwargs)

    with pytest.raises(error):
        service.record_decision(
            business_id="business-1",
            project_id="project-1",
            job_id="job-1",
            **values,
        )
