from pathlib import Path

db = Path("app/persistence/database.py")
source = db.read_text()

if "SCHEMA_VERSION = 22" not in source:
    raise SystemExit("STOP: expected schema version 22.")
if "21: _migrate_v21_to_v22," not in source:
    raise SystemExit("STOP: expected v21 migration registry entry.")
if "def _migrate_v22_to_v23(" in source:
    raise SystemExit("STOP: v23 migration already exists.")

migration = r'''

def _migrate_v22_to_v23(connection: sqlite3.Connection) -> None:
    """Create immutable, founder-authorised Forge acceptance decisions."""
    connection.execute("""
        CREATE TABLE forge_user_acceptance_decisions (
            decision_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            candidate_sha256 TEXT NOT NULL
                CHECK(
                    length(candidate_sha256) = 64
                    AND candidate_sha256 = lower(candidate_sha256)
                    AND candidate_sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            sentinel_assessment_id TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            decision TEXT NOT NULL
                CHECK(decision IN ('accepted', 'changes_requested')),
            live_test_confirmed INTEGER NOT NULL
                CHECK(live_test_confirmed IN (0, 1)),
            limitations_disclosed INTEGER NOT NULL
                CHECK(limitations_disclosed IN (0, 1)),
            feedback TEXT NOT NULL DEFAULT ''
                CHECK(length(CAST(feedback AS BLOB)) <= 4096),
            created_at TEXT NOT NULL,

            FOREIGN KEY(business_id, project_id, job_id)
                REFERENCES forge_jobs(business_id, project_id, job_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(sentinel_assessment_id)
                REFERENCES forge_sentinel_assessments(assessment_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(actor_user_id)
                REFERENCES platform_founders(user_id)
                ON DELETE RESTRICT,

            CHECK(
                decision != 'accepted'
                OR (live_test_confirmed = 1 AND limitations_disclosed = 1)
            ),
            CHECK(
                decision != 'changes_requested'
                OR length(trim(feedback)) > 0
            )
        )
    """)

    connection.execute("""
        CREATE INDEX idx_forge_acceptance_job
        ON forge_user_acceptance_decisions(
            business_id, project_id, job_id, created_at
        )
    """)

    connection.execute("""
        CREATE INDEX idx_forge_acceptance_artifact
        ON forge_user_acceptance_decisions(
            business_id, project_id, job_id, artifact_ref, candidate_sha256
        )
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_no_update
        BEFORE UPDATE ON forge_user_acceptance_decisions
        BEGIN
            SELECT RAISE(ABORT, 'Forge acceptance decisions are immutable');
        END
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_no_delete
        BEFORE DELETE ON forge_user_acceptance_decisions
        BEGIN
            SELECT RAISE(ABORT, 'Forge acceptance decisions are immutable');
        END
    """)

    connection.execute("""
        CREATE TRIGGER forge_acceptance_validate_insert
        BEFORE INSERT ON forge_user_acceptance_decisions
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM platform_founders f
                    WHERE f.user_id = NEW.actor_user_id AND f.active = 1
                )
                THEN RAISE(ABORT, 'Active founder authority required')
            END;

            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM forge_jobs j
                    WHERE j.business_id = NEW.business_id
                      AND j.project_id = NEW.project_id
                      AND j.job_id = NEW.job_id
                      AND j.status = 'completed_vaulted'
                )
                THEN RAISE(ABORT, 'Completed unlocked Forge job required')
            END;

            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM forge_sentinel_assessments a
                    WHERE a.assessment_id = NEW.sentinel_assessment_id
                      AND a.business_id = NEW.business_id
                      AND a.project_id = NEW.project_id
                      AND a.job_id = NEW.job_id
                      AND a.artifact_ref = NEW.artifact_ref
                      AND a.candidate_sha256 = NEW.candidate_sha256
                )
                THEN RAISE(ABORT, 'Matching Sentinel assessment required')
            END;

            SELECT CASE
                WHEN (
                    SELECT COUNT(*)
                    FROM forge_sentinel_guard_results r
                    WHERE r.assessment_id = NEW.sentinel_assessment_id
                      AND r.verdict = 'PASS'
                      AND r.artifact_ref = NEW.artifact_ref
                      AND r.candidate_sha256 = NEW.candidate_sha256
                ) != 5
                THEN RAISE(ABORT, 'All five Sentinel Guards must PASS')
            END;
        END
    """)


'''

source = source.replace(
    "MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {",
    migration + "\nMIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {",
    1,
)
source = source.replace("SCHEMA_VERSION = 22", "SCHEMA_VERSION = 23", 1)
source = source.replace(
    "    21: _migrate_v21_to_v22,\n",
    "    21: _migrate_v21_to_v22,\n    22: _migrate_v22_to_v23,\n",
    1,
)

if "22: _migrate_v22_to_v23," not in source:
    raise SystemExit("STOP: migration registry update failed.")

db.write_text(source)
print("Updated database migration to schema v23.")


Path("app/forge/acceptance_store.py").write_text('''"""Append-only persistence for founder Forge acceptance decisions."""

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
''')
print("Created app/forge/acceptance_store.py.")


Path("app/forge/acceptance_service.py").write_text('''"""Founder-authorised Forge user acceptance workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.forge.acceptance_store import (
    ForgeAcceptanceDecision,
    ForgeAcceptanceStore,
)
from app.forge.sentinel_coordinator import ForgeSentinelCoordinator


class ForgeAcceptanceServiceError(RuntimeError):
    """Raised when a candidate is not eligible for user acceptance."""


@dataclass(frozen=True)
class ForgeAcceptanceResult:
    decision: ForgeAcceptanceDecision
    evidence: tuple[Any, ...]


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
            raise TypeError("sentinel_coordinator must be a ForgeSentinelCoordinator.")
        self._store = store
        self._sentinel_coordinator = sentinel_coordinator

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

        digest = assessment.get("candidate_sha256")
        assessment_id = assessment.get("assessment_id")
        if not isinstance(digest, str) or not isinstance(assessment_id, str):
            raise ForgeAcceptanceServiceError(
                "Sentinel approval lacks its assessment identity or digest."
            )

        # Build the evidence before committing the decision. A change request
        # deliberately does not create user_acceptance PASS evidence.
        from datetime import datetime, timezone
        from app.forge.evidence import (
            EvidenceOrigin, EvidenceOutcome, ForgeEvidence,
        )
        from app.forge.engineering_standard import ForgeStage

        evidence = []
        for requirement, confirmed in (
            ("user_live_test", live_test_confirmed),
            ("limitations_disclosed", limitations_disclosed),
        ):
            if confirmed:
                evidence.append(ForgeEvidence(
                    evidence_id=f"pending:{requirement}",
                    stage=ForgeStage.USER_ACCEPTANCE,
                    requirement=requirement,
                    outcome=EvidenceOutcome.PASS,
                    origin=EvidenceOrigin.USER_ACCEPTANCE,
                    artifact_ref=artifact_ref,
                    artifact_sha256=digest,
                    verifier_id=actor_user_id,
                    verified_at=datetime.now(timezone.utc),
                    notes="Explicit founder confirmation.",
                ))

        if decision == "accepted":
            evidence.append(ForgeEvidence(
                evidence_id="pending:user_acceptance",
                stage=ForgeStage.USER_ACCEPTANCE,
                requirement="user_acceptance",
                outcome=EvidenceOutcome.PASS,
                origin=EvidenceOrigin.USER_ACCEPTANCE,
                artifact_ref=artifact_ref,
                artifact_sha256=digest,
                verifier_id=actor_user_id,
                verified_at=datetime.now(timezone.utc),
                notes="Founder accepted this exact Sentinel-approved candidate.",
            ))

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

        # Replace temporary evidence IDs with the durable decision ID.
        from dataclasses import replace
        evidence = tuple(
            replace(item, evidence_id=item.evidence_id.replace(
                "pending:", f"{record.decision_id}:"
            ))
            for item in evidence
        )
        return ForgeAcceptanceResult(decision=record, evidence=evidence)
''')

print("Created app/forge/acceptance_service.py.")
print("Patch applied. Database migration has NOT been run.")
