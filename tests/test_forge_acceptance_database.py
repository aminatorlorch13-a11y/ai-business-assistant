from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.forge.job import ForgeJob
from app.forge.job_store import ForgeJobStore
from app.forge.project_store import ForgeProjectStore
from app.forge.sentinel_guards import (
    GUARD_IDS,
    ForgeSentinelAssessmentService,
    GuardDecision,
    GuardReviewer,
    GuardVerdict,
)
from app.forge.sentinel_store import ForgeSentinelStore
from app.persistence.database import SQLiteDatabase


BUSINESS = "business-acceptance"
PROJECT = "project-acceptance"
JOB = "job-acceptance"
FOUNDER = "founder-acceptance"
ARTIFACT = "artifact://candidate/acceptance-test"
CONTENT = b"immutable candidate bytes for acceptance database tests"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def acceptance_db(tmp_path):
    db = SQLiteDatabase(tmp_path / "acceptance.sqlite3")
    db.initialize()

    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (BUSINESS, "Test Business", "Owner", "Assistant", "male"),
        )
        conn.execute(
            "INSERT INTO users(user_id, display_name, email) VALUES (?, ?, ?)",
            (FOUNDER, "Test Founder", "founder@example.test"),
        )
        conn.execute(
            "INSERT INTO platform_founders(user_id, active) VALUES (?, 1)",
            (FOUNDER,),
        )

    ForgeProjectStore(db).create(BUSINESS, PROJECT, "Acceptance test")
    now = datetime.now(timezone.utc)

    ForgeJobStore(db).create(
        ForgeJob(
            job_id=JOB,
            business_id=BUSINESS,
            project_id=PROJECT,
            job_type="code_review",
            created_at=now,
            updated_at=now,
        )
    )

    with db.transaction() as conn:
        conn.execute(
            """
            UPDATE forge_jobs
            SET status = 'completed_vaulted',
                phase = 'completed',
                progress = 100,
                started_at = created_at,
                completed_at = ?,
                checkpoint_json = ?
            WHERE business_id = ? AND project_id = ? AND job_id = ?
            """,
            (
                now.isoformat(),
                json.dumps({"artifact_reference": ARTIFACT}),
                BUSINESS,
                PROJECT,
                JOB,
            ),
        )

    sentinel = ForgeSentinelStore(db)
    passing_reviewers = tuple(
        GuardReviewer(
            guard_id=guard_id,
            implementation_id=f"db-test-reviewer-{index}",
            review=lambda _input: GuardDecision(GuardVerdict.PASS),
        )
        for index, guard_id in enumerate(GUARD_IDS, start=1)
    )
    assessment = ForgeSentinelAssessmentService(passing_reviewers).assess(
        artifact_ref=ARTIFACT,
        candidate_reader=lambda: CONTENT,
    )
    assessment_id = sentinel.record(
        business_id=BUSINESS,
        project_id=PROJECT,
        job_id=JOB,
        assessment=assessment,
    )

    return db, sentinel, assessment_id


def insert_decision(db, assessment_id, **overrides):
    values = {
        "decision_id": "decision-db-test",
        "business_id": BUSINESS,
        "project_id": PROJECT,
        "job_id": JOB,
        "artifact_ref": ARTIFACT,
        "candidate_sha256": DIGEST,
        "sentinel_assessment_id": assessment_id,
        "actor_user_id": FOUNDER,
        "decision": "accepted",
        "live_test_confirmed": 1,
        "limitations_disclosed": 1,
        "feedback": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)

    with db.transaction() as conn:
        conn.execute(
            f"INSERT INTO forge_user_acceptance_decisions ({columns}) "
            f"VALUES ({placeholders})",
            tuple(values.values()),
        )

    return values["decision_id"]


def test_database_accepts_valid_decision_after_five_guard_passes(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db
    decision_id = insert_decision(db, assessment_id)

    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM forge_user_acceptance_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        guards = conn.execute(
            """
            SELECT guard_id, verdict FROM forge_sentinel_guard_results
            WHERE assessment_id = ?
            """,
            (assessment_id,),
        ).fetchall()

    assert row["decision"] == "accepted"
    assert row["actor_user_id"] == FOUNDER
    assert len(guards) == 5
    assert {item["verdict"] for item in guards} == {"PASS"}


def test_database_rejects_inactive_founder(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db
    with db.transaction() as conn:
        conn.execute(
            "UPDATE platform_founders SET active = 0 WHERE user_id = ?",
            (FOUNDER,),
        )

    with pytest.raises(sqlite3.IntegrityError, match="Active founder authority"):
        insert_decision(db, assessment_id)


def test_database_rejects_locked_job(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db
    with db.transaction() as conn:
        conn.execute(
            """
            UPDATE forge_jobs SET status = 'completed_vaulted_locked'
            WHERE business_id = ? AND project_id = ? AND job_id = ?
            """,
            (BUSINESS, PROJECT, JOB),
        )

    with pytest.raises(sqlite3.IntegrityError, match="Completed unlocked Forge job"):
        insert_decision(db, assessment_id)


def test_database_rejects_artifact_not_bound_to_assessment(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db

    with pytest.raises(sqlite3.IntegrityError, match="Matching Sentinel assessment"):
        insert_decision(
            db,
            assessment_id,
            artifact_ref="artifact://candidate/another-revision",
        )


def test_database_rejects_blocked_sentinel_assessment(acceptance_db):
    db, sentinel, _passing_id = acceptance_db

    reviewers = tuple(
        GuardReviewer(
            guard_id=guard_id,
            implementation_id=f"blocked-reviewer-{index}",
            review=lambda _input: GuardDecision(
                GuardVerdict.FAIL if _input.guard_id == GUARD_IDS[0]
                else GuardVerdict.PASS
            ),
        )
        for index, guard_id in enumerate(GUARD_IDS, start=1)
    )
    blocked = ForgeSentinelAssessmentService(reviewers).assess(
        artifact_ref=ARTIFACT,
        candidate_reader=lambda: CONTENT,
    )
    blocked_id = sentinel.record(
        business_id=BUSINESS,
        project_id=PROJECT,
        job_id=JOB,
        assessment=blocked,
    )

    with pytest.raises(sqlite3.IntegrityError, match="Matching Sentinel assessment"):
        insert_decision(db, blocked_id)


def test_database_rejects_acceptance_without_both_confirmations(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db

    with pytest.raises(sqlite3.IntegrityError):
        insert_decision(db, assessment_id, live_test_confirmed=0)

    with pytest.raises(sqlite3.IntegrityError):
        insert_decision(db, assessment_id, limitations_disclosed=0)


def test_database_rejects_changes_requested_without_feedback(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db

    with pytest.raises(sqlite3.IntegrityError):
        insert_decision(
            db,
            assessment_id,
            decision="changes_requested",
            feedback="   ",
        )


def test_database_accepts_changes_requested_with_feedback(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db
    decision_id = insert_decision(
        db,
        assessment_id,
        decision="changes_requested",
        live_test_confirmed=0,
        limitations_disclosed=0,
        feedback="Please correct the navigation issue.",
    )

    with db.connection() as conn:
        row = conn.execute(
            "SELECT decision, feedback FROM forge_user_acceptance_decisions "
            "WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()

    assert row["decision"] == "changes_requested"
    assert row["feedback"] == "Please correct the navigation issue."


def test_database_rejects_update_and_delete(acceptance_db):
    db, _sentinel, assessment_id = acceptance_db
    decision_id = insert_decision(db, assessment_id)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.transaction() as conn:
            conn.execute(
                "UPDATE forge_user_acceptance_decisions "
                "SET feedback = 'tampered' WHERE decision_id = ?",
                (decision_id,),
            )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with db.transaction() as conn:
            conn.execute(
                "DELETE FROM forge_user_acceptance_decisions WHERE decision_id = ?",
                (decision_id,),
            )

    with db.connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM forge_user_acceptance_decisions "
            "WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()[0]

    assert count == 1
