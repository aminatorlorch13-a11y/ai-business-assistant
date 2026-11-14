"""Append-only persistence for founder Forge acceptance decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import json
import uuid

from app.persistence.database import SQLiteDatabase


class ForgeAcceptanceStoreError(RuntimeError):
    """Raised when a Forge acceptance decision cannot be persisted."""


@dataclass(frozen=True)
class ForgeAcceptanceDecision:
    decision_id: str
    business_id: str
    project_id: str
    job_id: str
    artifact_ref: str
    candidate_sha256: str
    sentinel_assessment_id: str
    actor_user_id: str
    decision: str
    live_test_confirmed: bool
    limitations_disclosed: bool
    feedback: str
    created_at: str


class ForgeAcceptanceStore:
    """Persist immutable founder decisions with tenant and job isolation."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def current_artifact(
        self, *, business_id: str, project_id: str, job_id: str
    ) -> str:
        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT status, checkpoint_json FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (business_id, project_id, job_id),
            ).fetchone()

        if row is None:
            raise ForgeAcceptanceStoreError("Forge job was not found.")
        if row["status"] != "completed_vaulted":
            raise ForgeAcceptanceStoreError(
                "The job must be completed and safely vaulted."
            )
        try:
            checkpoint = json.loads(row["checkpoint_json"] or "{}")
        except (TypeError, ValueError) as exc:
            raise ForgeAcceptanceStoreError("Invalid Forge job checkpoint.") from exc

        artifact_ref = (
            checkpoint.get("artifact_reference")
            if isinstance(checkpoint, dict) else None
        )
        if not isinstance(artifact_ref, str) or not artifact_ref:
            raise ForgeAcceptanceStoreError(
                "The job has no current artifact checkpoint."
            )
        return artifact_ref

    def record(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        artifact_ref: str,
        candidate_sha256: str,
        sentinel_assessment_id: str,
        actor_user_id: str,
        decision: str,
        live_test_confirmed: bool,
        limitations_disclosed: bool,
        feedback: str = "",
    ) -> ForgeAcceptanceDecision:
        for name, value in {
            "business_id": business_id,
            "project_id": project_id,
            "job_id": job_id,
            "artifact_ref": artifact_ref,
            "candidate_sha256": candidate_sha256,
            "sentinel_assessment_id": sentinel_assessment_id,
            "actor_user_id": actor_user_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty text.")
            if value != value.strip():
                raise ValueError(f"{name} must not have outer whitespace.")

        if decision not in {"accepted", "changes_requested"}:
            raise ValueError("Unsupported acceptance decision.")
        if type(live_test_confirmed) is not bool:
            raise TypeError("live_test_confirmed must be bool.")
        if type(limitations_disclosed) is not bool:
            raise TypeError("limitations_disclosed must be bool.")
        if not isinstance(feedback, str) or len(feedback.encode("utf-8")) > 4096:
            raise ValueError("feedback must be text no longer than 4096 bytes.")
        if decision == "accepted" and not (
            live_test_confirmed and limitations_disclosed
        ):
            raise ValueError(
                "Acceptance requires live-test and limitations confirmation."
            )
        if decision == "changes_requested" and not feedback.strip():
            raise ValueError("A change request requires feedback.")

        decision_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.transaction() as connection:
            founder = connection.execute(
                "SELECT active FROM platform_founders WHERE user_id = ?",
                (actor_user_id,),
            ).fetchone()
            if founder is None or founder["active"] != 1:
                raise ForgeAcceptanceStoreError(
                    "An active platform founder must record this decision."
                )

            job = connection.execute(
                """
                SELECT status, checkpoint_json FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (business_id, project_id, job_id),
            ).fetchone()
            if job is None or job["status"] != "completed_vaulted":
                raise ForgeAcceptanceStoreError(
                    "The job is missing or is not completed and unlocked."
                )
            try:
                checkpoint = json.loads(job["checkpoint_json"] or "{}")
            except (TypeError, ValueError) as exc:
                raise ForgeAcceptanceStoreError(
                    "Invalid Forge job checkpoint."
                ) from exc
            if (
                not isinstance(checkpoint, dict)
                or checkpoint.get("artifact_reference") != artifact_ref
            ):
                raise ForgeAcceptanceStoreError(
                    "Candidate is not the job's current checkpoint artifact."
                )

            connection.execute(
                """
                INSERT INTO forge_user_acceptance_decisions (
                    decision_id, business_id, project_id, job_id,
                    artifact_ref, candidate_sha256, sentinel_assessment_id,
                    actor_user_id, decision, live_test_confirmed,
                    limitations_disclosed, feedback, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id, business_id, project_id, job_id,
                    artifact_ref, candidate_sha256, sentinel_assessment_id,
                    actor_user_id, decision, int(live_test_confirmed),
                    int(limitations_disclosed), feedback, created_at,
                ),
            )

        return ForgeAcceptanceDecision(
            decision_id=decision_id,
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
            artifact_ref=artifact_ref,
            candidate_sha256=candidate_sha256,
            sentinel_assessment_id=sentinel_assessment_id,
            actor_user_id=actor_user_id,
            decision=decision,
            live_test_confirmed=live_test_confirmed,
            limitations_disclosed=limitations_disclosed,
            feedback=feedback,
            created_at=created_at,
        )

    def list_for_job(
        self, *, business_id: str, project_id: str, job_id: str
    ) -> list[dict[str, Any]]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM forge_user_acceptance_decisions
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                ORDER BY created_at ASC, decision_id ASC
                """,
                (business_id, project_id, job_id),
            ).fetchall()
        return [dict(row) for row in rows]
