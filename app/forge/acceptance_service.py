"""Founder-authorised Forge user acceptance workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.forge.acceptance_store import (
    ForgeAcceptanceDecision,
    ForgeAcceptanceStore,
)
from app.forge.sentinel_coordinator import ForgeSentinelCoordinator
from app.forge.evidence import (
    EvidenceOrigin,
    EvidenceOutcome,
    ForgeEvidence,
)
from app.forge.engineering_standard import ForgeStage


class ForgeAcceptanceServiceError(RuntimeError):
    """Raised when a candidate is not eligible for user acceptance."""


@dataclass(frozen=True)
class ForgeAcceptanceResult:
    decision: ForgeAcceptanceDecision
    evidence: tuple[ForgeEvidence, ...]


class ForgeAcceptanceService:
    """Require current checkpoint, Sentinel approval, and founder attestations."""

    def __init__(
        self,
        *,
        store: ForgeAcceptanceStore,
        sentinel_coordinator: ForgeSentinelCoordinator,
    ) -> None:
        if not isinstance(store, ForgeAcceptanceStore):
            raise TypeError("store must be a ForgeAcceptanceStore.")
        if not isinstance(sentinel_coordinator, ForgeSentinelCoordinator):
            raise TypeError(
                "sentinel_coordinator must be a ForgeSentinelCoordinator."
            )
        self._store = store
        self._sentinel_coordinator = sentinel_coordinator

    @staticmethod
    def _validate_decision_input(
        *,
        actor_user_id: str,
        decision: str,
        live_test_confirmed: bool,
        limitations_disclosed: bool,
        feedback: str,
    ) -> None:
        if (
            not isinstance(actor_user_id, str)
            or not actor_user_id.strip()
            or actor_user_id != actor_user_id.strip()
        ):
            raise ValueError("actor_user_id must be non-empty trimmed text.")

        if decision not in {"accepted", "changes_requested"}:
            raise ValueError("Unsupported acceptance decision.")

        if type(live_test_confirmed) is not bool:
            raise TypeError("live_test_confirmed must be bool.")
        if type(limitations_disclosed) is not bool:
            raise TypeError("limitations_disclosed must be bool.")

        if not isinstance(feedback, str):
            raise TypeError("feedback must be text.")
        if len(feedback.encode("utf-8")) > 4096:
            raise ValueError("feedback must not exceed 4096 UTF-8 bytes.")

        if decision == "accepted" and not (
            live_test_confirmed and limitations_disclosed
        ):
            raise ValueError(
                "Acceptance requires live-test and limitations confirmation."
            )

        if decision == "changes_requested" and not feedback.strip():
            raise ValueError("A change request requires feedback.")

    @staticmethod
    def evidence_for_decision(
        decision: ForgeAcceptanceDecision,
    ) -> tuple[ForgeEvidence, ...]:
        """Reconstruct immutable gate evidence from a persisted decision.

        The acceptance decision row is the durable source of truth. Evidence
        identifiers are deterministic within that decision, so retrieval does
        not create duplicate evidence or imply a second founder action.
        """
        if not isinstance(decision, ForgeAcceptanceDecision):
            raise TypeError("decision must be a ForgeAcceptanceDecision.")

        try:
            verified_at = datetime.fromisoformat(decision.created_at)
        except (TypeError, ValueError) as exc:
            raise ForgeAcceptanceServiceError(
                "The persisted decision timestamp is invalid."
            ) from exc

        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise ForgeAcceptanceServiceError(
                "The persisted decision timestamp must be timezone-aware."
            )

        if decision.decision not in {"accepted", "changes_requested"}:
            raise ForgeAcceptanceServiceError(
                "The persisted decision has an unsupported value."
            )

        confirmations = (
            ("user_live_test", decision.live_test_confirmed),
            ("limitations_disclosed", decision.limitations_disclosed),
            ("user_acceptance", decision.decision == "accepted"),
        )

        records = []
        for requirement, confirmed in confirmations:
            if requirement == "user_acceptance":
                outcome = (
                    EvidenceOutcome.PASS
                    if confirmed else EvidenceOutcome.FAIL
                )
            else:
                outcome = (
                    EvidenceOutcome.PASS
                    if confirmed else EvidenceOutcome.INCONCLUSIVE
                )

            records.append(
                ForgeEvidence(
                    evidence_id=f"{decision.decision_id}:{requirement}",
                    stage=ForgeStage.USER_ACCEPTANCE,
                    requirement=requirement,
                    outcome=outcome,
                    origin=EvidenceOrigin.USER_ACCEPTANCE,
                    artifact_ref=decision.artifact_ref,
                    artifact_sha256=decision.candidate_sha256,
                    verifier_id=decision.actor_user_id,
                    verified_at=verified_at,
                    notes=(
                        "Founder confirmation recorded in immutable "
                        "acceptance decision."
                        if confirmed else
                        "This requirement was not confirmed by the founder."
                    ),
                )
            )

        return tuple(records)

    def record_decision(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        actor_user_id: str,
        decision: str,
        live_test_confirmed: bool,
        limitations_disclosed: bool,
        feedback: str = "",
    ) -> ForgeAcceptanceResult:
        # Reject malformed requests before querying candidate or Sentinel state.
        self._validate_decision_input(
            actor_user_id=actor_user_id,
            decision=decision,
            live_test_confirmed=live_test_confirmed,
            limitations_disclosed=limitations_disclosed,
            feedback=feedback,
        )

        artifact_ref = self._store.current_artifact(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
        )

        try:
            assessment = self._sentinel_coordinator.require_approved(
                business_id=business_id,
                project_id=project_id,
                job_id=job_id,
                artifact_reference=artifact_ref,
            )
        except Exception as exc:
            raise ForgeAcceptanceServiceError(
                "The exact current candidate has not passed all Sentinel Guards."
            ) from exc

        if not isinstance(assessment, dict):
            raise ForgeAcceptanceServiceError(
                "Sentinel approval returned an invalid assessment."
            )

        digest = assessment.get("candidate_sha256")
        assessment_id = assessment.get("assessment_id")
        if (
            not isinstance(digest, str)
            or not isinstance(assessment_id, str)
            or not digest
            or not assessment_id
        ):
            raise ForgeAcceptanceServiceError(
                "Sentinel approval lacks its assessment identity or digest."
            )

        record = self._store.record(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
            artifact_ref=artifact_ref,
            candidate_sha256=digest,
            sentinel_assessment_id=assessment_id,
            actor_user_id=actor_user_id,
            decision=decision,
            live_test_confirmed=live_test_confirmed,
            limitations_disclosed=limitations_disclosed,
            feedback=feedback,
        )

        # Evidence is reconstructed from the persisted immutable decision.
        return ForgeAcceptanceResult(
            decision=record,
            evidence=self.evidence_for_decision(record),
        )
