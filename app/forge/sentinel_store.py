"""Append-only durable storage for Forge Sentinel assessments."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import uuid

from app.persistence.database import SQLiteDatabase
from app.forge.sentinel_guards import (
    GUARD_IDS,
    AssessmentStatus,
    GuardVerdict,
    SentinelAssessment,
    assessment_was_issued_by_service,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ForgeSentinelStore:
    """Persist immutable Sentinel assessment runs and their Guard results."""

    def __init__(self, database: SQLiteDatabase) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    @staticmethod
    def _validate_scope(
        business_id: str,
        project_id: str,
        job_id: str,
    ) -> None:
        for name, value in (
            ("business_id", business_id),
            ("project_id", project_id),
            ("job_id", job_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string.")
            if len(value) > 255:
                raise ValueError(f"{name} is too long.")

    @staticmethod
    def _validate_assessment(assessment: SentinelAssessment) -> None:
        if not assessment_was_issued_by_service(assessment):
            raise ValueError(
                "Assessment was not issued by ForgeSentinelAssessmentService."
            )

        if (
            not isinstance(assessment.artifact_ref, str)
            or not assessment.artifact_ref.strip()
            or len(assessment.artifact_ref) > 512
        ):
            raise ValueError("Invalid assessment artifact reference.")

        if (
            not isinstance(assessment.candidate_sha256, str)
            or not _SHA256_RE.fullmatch(assessment.candidate_sha256)
        ):
            raise ValueError("Invalid candidate SHA-256 digest.")

        if type(assessment.status) is not AssessmentStatus:
            raise ValueError("Invalid assessment status.")

        results = assessment.results
        if type(results) is not tuple or not 1 <= len(results) <= 5:
            raise ValueError("Assessment must contain a sequential result prefix.")

        for index, result in enumerate(results):
            if result.guard_id != GUARD_IDS[index]:
                raise ValueError("Guard results are not in strict sequence.")
            if result.artifact_ref != assessment.artifact_ref:
                raise ValueError("Guard result artifact reference mismatch.")
            if result.candidate_sha256 != assessment.candidate_sha256:
                raise ValueError("Guard result digest mismatch.")
            if type(result.verdict) is not GuardVerdict:
                raise ValueError("Invalid Guard verdict.")
            if not isinstance(result.reviewed_at, str) or not result.reviewed_at:
                raise ValueError("Guard result timestamp is missing.")
            if result.implementation_id is not None and (
                not isinstance(result.implementation_id, str)
                or not result.implementation_id.strip()
            ):
                raise ValueError("Invalid Guard implementation identity.")
            if type(result.findings) is not tuple:
                raise ValueError("Guard findings must be a tuple.")
            if any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 2000
                for item in result.findings
            ):
                raise ValueError("Invalid Guard finding.")

            if index < len(results) - 1 and result.verdict is not GuardVerdict.PASS:
                raise ValueError("A non-PASS Guard cannot be followed by another Guard.")

        if assessment.status is AssessmentStatus.READY_FOR_USER_ACCEPTANCE:
            if len(results) != 5 or any(
                result.verdict is not GuardVerdict.PASS for result in results
            ):
                raise ValueError("User acceptance requires five PASS results.")
            if assessment.blocked_at_guard is not None:
                raise ValueError("A passing assessment cannot have a blocked Guard.")
        else:
            if results[-1].verdict is GuardVerdict.PASS:
                raise ValueError("A blocked assessment must end with a non-PASS result.")
            if assessment.blocked_at_guard != results[-1].guard_id:
                raise ValueError("Blocked Guard does not match the final result.")

    def record(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        assessment: SentinelAssessment,
    ) -> str:
        """Append one assessment run. Existing runs are never overwritten."""
        self._validate_scope(business_id, project_id, job_id)
        self._validate_assessment(assessment)

        assessment_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO forge_sentinel_assessments (
                    assessment_id, business_id, project_id, job_id,
                    artifact_ref, candidate_sha256, status,
                    blocked_at_guard, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment_id,
                    business_id,
                    project_id,
                    job_id,
                    assessment.artifact_ref,
                    assessment.candidate_sha256,
                    assessment.status.value,
                    assessment.blocked_at_guard,
                    created_at,
                ),
            )

            for result in assessment.results:
                connection.execute(
                    """
                    INSERT INTO forge_sentinel_guard_results (
                        assessment_id, business_id, project_id, job_id,
                        guard_id, implementation_id, artifact_ref,
                        candidate_sha256, verdict, findings_json, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment_id,
                        business_id,
                        project_id,
                        job_id,
                        result.guard_id,
                        result.implementation_id,
                        result.artifact_ref,
                        result.candidate_sha256,
                        result.verdict.value,
                        json.dumps(
                            result.findings,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        result.reviewed_at,
                    ),
                )

        return assessment_id

    def get(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        assessment_id: str,
    ) -> dict | None:
        """Retrieve one assessment only within its complete tenant/job scope."""
        self._validate_scope(business_id, project_id, job_id)
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise ValueError("assessment_id must be non-empty.")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT assessment_id, business_id, project_id, job_id,
                       artifact_ref, candidate_sha256, status,
                       blocked_at_guard, created_at
                FROM forge_sentinel_assessments
                WHERE assessment_id = ?
                  AND business_id = ?
                  AND project_id = ?
                  AND job_id = ?
                """,
                (assessment_id, business_id, project_id, job_id),
            ).fetchone()

            if row is None:
                return None

            result_rows = connection.execute(
                """
                SELECT guard_id, implementation_id, artifact_ref,
                       candidate_sha256, verdict, findings_json, reviewed_at
                FROM forge_sentinel_guard_results
                WHERE assessment_id = ?
                  AND business_id = ?
                  AND project_id = ?
                  AND job_id = ?
                ORDER BY
                    CASE guard_id
                        WHEN 'sentinel-guard-1' THEN 1
                        WHEN 'sentinel-guard-2' THEN 2
                        WHEN 'sentinel-guard-3' THEN 3
                        WHEN 'sentinel-guard-4' THEN 4
                        WHEN 'sentinel-guard-5' THEN 5
                    END
                """,
                (assessment_id, business_id, project_id, job_id),
            ).fetchall()

        return {
            "assessment_id": row["assessment_id"],
            "business_id": row["business_id"],
            "project_id": row["project_id"],
            "job_id": row["job_id"],
            "artifact_ref": row["artifact_ref"],
            "candidate_sha256": row["candidate_sha256"],
            "status": row["status"],
            "blocked_at_guard": row["blocked_at_guard"],
            "created_at": row["created_at"],
            "results": [
                {
                    "guard_id": item["guard_id"],
                    "implementation_id": item["implementation_id"],
                    "artifact_ref": item["artifact_ref"],
                    "candidate_sha256": item["candidate_sha256"],
                    "verdict": item["verdict"],
                    "findings": json.loads(item["findings_json"]),
                    "reviewed_at": item["reviewed_at"],
                }
                for item in result_rows
            ],
        }

    def latest_for_artifact(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
        artifact_ref: str,
    ) -> dict | None:
        """Retrieve the newest assessment for one exact artifact in its job scope."""
        self._validate_scope(business_id, project_id, job_id)
        if not isinstance(artifact_ref, str) or not artifact_ref.strip():
            raise ValueError("artifact_ref must be non-empty.")

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT assessment_id
                FROM forge_sentinel_assessments
                WHERE business_id = ?
                  AND project_id = ?
                  AND job_id = ?
                  AND artifact_ref = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (business_id, project_id, job_id, artifact_ref),
            ).fetchone()

        if row is None:
            return None

        return self.get(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
            assessment_id=row["assessment_id"],
        )

    def latest_for_job(
        self,
        *,
        business_id: str,
        project_id: str,
        job_id: str,
    ) -> dict | None:
        """Retrieve the newest assessment for a tenant-scoped Forge job."""
        self._validate_scope(business_id, project_id, job_id)

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT assessment_id
                FROM forge_sentinel_assessments
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (business_id, project_id, job_id),
            ).fetchone()

        if row is None:
            return None

        return self.get(
            business_id=business_id,
            project_id=project_id,
            job_id=job_id,
            assessment_id=row["assessment_id"],
        )
