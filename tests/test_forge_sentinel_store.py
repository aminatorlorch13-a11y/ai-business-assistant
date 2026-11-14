from datetime import datetime, timezone
import sqlite3

import pytest

from app.forge.job import ForgeJob
from app.forge.job_store import ForgeJobStore
from app.forge.project_store import ForgeProjectStore
from app.forge.sentinel_guards import (
    GUARD_IDS,
    AssessmentStatus,
    ForgeSentinelAssessmentService,
    GuardDecision,
    GuardReviewer,
    GuardVerdict,
    SentinelAssessment,
)
from app.forge.sentinel_store import ForgeSentinelStore
from app.persistence.database import SQLiteDatabase


@pytest.fixture
def sentinel_env(tmp_path):
    database = SQLiteDatabase(tmp_path / "sentinel-test.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        for business_id in ("business-1", "business-2"):
            connection.execute(
                """
                INSERT INTO businesses (
                    business_id, name, owner_name, assistant_name,
                    assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, "Business", "Owner", "Assistant", "male"),
            )

    projects = ForgeProjectStore(database)
    projects.create("business-1", "project-1", "Project")
    projects.create("business-2", "project-1", "Project")

    jobs = ForgeJobStore(database)
    now = datetime.now(timezone.utc)

    for business_id in ("business-1", "business-2"):
        jobs.create(
            ForgeJob(
                job_id="job-1",
                business_id=business_id,
                project_id="project-1",
                job_type="code_review",
                created_at=now,
                updated_at=now,
            )
        )

    return database, ForgeSentinelStore(database)


def make_passing_assessment():
    reviewers = tuple(
        GuardReviewer(
            guard_id=guard_id,
            implementation_id=f"test-reviewer-{index}",
            review=lambda _input: GuardDecision(GuardVerdict.PASS),
        )
        for index, guard_id in enumerate(GUARD_IDS, start=1)
    )

    service = ForgeSentinelAssessmentService(reviewers)
    return service.assess(
        artifact_ref="artifact://candidate/test-1",
        candidate_reader=lambda: b"immutable candidate bytes",
    )


def record_passing_assessment(store):
    assessment = make_passing_assessment()
    assessment_id = store.record(
        business_id="business-1",
        project_id="project-1",
        job_id="job-1",
        assessment=assessment,
    )
    return assessment_id


def test_migration_creates_sentinel_tables_and_triggers(sentinel_env):
    database, _store = sentinel_env

    with database.connection() as connection:
        objects = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type IN ('table', 'trigger')
                """
            ).fetchall()
        }

    assert "forge_sentinel_assessments" in objects
    assert "forge_sentinel_guard_results" in objects
    assert "forge_sentinel_assessments_no_update" in objects
    assert "forge_sentinel_assessments_no_delete" in objects
    assert "forge_sentinel_results_no_update" in objects
    assert "forge_sentinel_results_no_delete" in objects
    assert "forge_sentinel_results_validate_insert" in objects


def test_service_assessment_is_persisted_and_retrieved(sentinel_env):
    _database, store = sentinel_env

    assessment_id = record_passing_assessment(store)

    found = store.get(
        business_id="business-1",
        project_id="project-1",
        job_id="job-1",
        assessment_id=assessment_id,
    )

    assert found is not None
    assert found["assessment_id"] == assessment_id
    assert found["status"] == AssessmentStatus.READY_FOR_USER_ACCEPTANCE.value
    assert found["blocked_at_guard"] is None
    assert len(found["results"]) == 5
    assert [item["guard_id"] for item in found["results"]] == list(GUARD_IDS)
    assert all(item["verdict"] == GuardVerdict.PASS.value for item in found["results"])


def test_assessment_lookup_is_tenant_and_job_scoped(sentinel_env):
    _database, store = sentinel_env
    assessment_id = record_passing_assessment(store)

    other_tenant = store.get(
        business_id="business-2",
        project_id="project-1",
        job_id="job-1",
        assessment_id=assessment_id,
    )

    wrong_project = store.get(
        business_id="business-1",
        project_id="wrong-project",
        job_id="job-1",
        assessment_id=assessment_id,
    )

    wrong_job = store.get(
        business_id="business-1",
        project_id="project-1",
        job_id="wrong-job",
        assessment_id=assessment_id,
    )

    assert other_tenant is None
    assert wrong_project is None
    assert wrong_job is None


def test_store_rejects_assessment_not_issued_by_service(sentinel_env):
    _database, store = sentinel_env

    fabricated = SentinelAssessment(
        artifact_ref="artifact://candidate/fabricated",
        candidate_sha256="0" * 64,
        status=AssessmentStatus.BLOCKED,
        results=(),
        blocked_at_guard=GUARD_IDS[0],
    )

    with pytest.raises(ValueError, match="not issued"):
        store.record(
            business_id="business-1",
            project_id="project-1",
            job_id="job-1",
            assessment=fabricated,
        )


def test_assessment_and_results_cannot_be_updated_or_deleted(sentinel_env):
    database, store = sentinel_env
    assessment_id = record_passing_assessment(store)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                UPDATE forge_sentinel_assessments
                SET status = status
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                DELETE FROM forge_sentinel_assessments
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                UPDATE forge_sentinel_guard_results
                SET verdict = verdict
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                DELETE FROM forge_sentinel_guard_results
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            )


def test_database_rejects_out_of_order_guard_result(sentinel_env):
    database, _store = sentinel_env
    assessment_id = "manual-sequence-test"
    digest = "0" * 64
    artifact_ref = "artifact://candidate/manual"
    reviewed_at = datetime.now(timezone.utc).isoformat()

    with pytest.raises(sqlite3.IntegrityError, match="sequence violation"):
        with database.transaction() as connection:
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
                    "business-1",
                    "project-1",
                    "job-1",
                    artifact_ref,
                    digest,
                    AssessmentStatus.BLOCKED.value,
                    GUARD_IDS[1],
                    reviewed_at,
                ),
            )

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
                    "business-1",
                    "project-1",
                    "job-1",
                    GUARD_IDS[1],
                    "manual-test",
                    artifact_ref,
                    digest,
                    GuardVerdict.FAIL.value,
                    "[]",
                    reviewed_at,
                ),
            )
