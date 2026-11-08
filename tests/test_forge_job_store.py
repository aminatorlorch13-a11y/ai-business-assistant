from datetime import datetime, timedelta, timezone
from dataclasses import replace
import time
import threading

import pytest

from app.forge.job import ForgeJob, ForgeJobStatus
from app.forge.task_spec import ForgeTaskSpec
from app.forge.worker import ForgeExecutionResult, ForgeWorker
from app.forge.worker_runtime import ForgeWorkerRunner
from app.forge.job_store import (
    ForgeJobAlreadyExistsError,
    ForgeJobConflictError,
    ForgeJobStore,
    ForgeTaskSpecIntegrityError,
)
from app.forge.project_store import ForgeProjectStore
from app.persistence.database import SQLiteDatabase


@pytest.fixture
def job_store(tmp_path):
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        for business_id in ("business-1", "business-2"):
            connection.execute(
                """
                INSERT INTO businesses(
                    business_id, name, owner_name, assistant_name,
                    assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, "Business", "Owner", "Assistant", "male"),
            )

    projects = ForgeProjectStore(database)
    projects.create("business-1", "project-1", "Project")
    projects.create("business-2", "project-1", "Project")

    return ForgeJobStore(database)


def make_job(**overrides):
    now = datetime.now(timezone.utc)
    values = {
        "job_id": "job-1",
        "business_id": "business-1",
        "project_id": "project-1",
        "job_type": "code_review",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return ForgeJob(**values)


def test_create_and_get_job(job_store):
    created = job_store.create(make_job())
    found = job_store.get("business-1", "project-1", "job-1")

    assert found == created
    assert found.revision == 1
    assert found.job.status is ForgeJobStatus.QUEUED


def test_same_job_id_can_belong_to_different_businesses(job_store):
    first = job_store.create(make_job())
    second = job_store.create(
        make_job(business_id="business-2")
    )

    assert first.job.business_id != second.job.business_id
    assert job_store.get("business-1", "project-1", "job-1") == first
    assert job_store.get("business-2", "project-1", "job-1") == second


def test_duplicate_job_is_rejected(job_store):
    job_store.create(make_job())

    with pytest.raises(ForgeJobAlreadyExistsError):
        job_store.create(make_job())


def test_job_lookup_is_business_scoped(job_store):
    job_store.create(make_job())

    assert job_store.get(
        "business-2", "project-1", "job-1"
    ) is None


def test_create_requires_existing_project(job_store):
    with pytest.raises(ValueError, match="existing project"):
        job_store.create(make_job(project_id="missing"))


def test_list_is_scoped_to_project(job_store):
    job_store.create(make_job())
    job_store.create(make_job(job_id="job-2"))
    job_store.create(make_job(business_id="business-2"))

    records = job_store.list_for_project("business-1", "project-1")

    assert {record.job.job_id for record in records} == {"job-1", "job-2"}


def test_update_increments_revision_and_preserves_checkpoint(job_store):
    created = job_store.create(make_job())
    running = created.job.transition(
        ForgeJobStatus.RUNNING,
        created.job.created_at + timedelta(seconds=1),
    )
    updated_job = running.save_checkpoint(
        {"step": "testing", "completed": ["unit", "integration"]},
        running.updated_at + timedelta(seconds=1),
    )

    updated = job_store.update(
        type(created)(job=updated_job, revision=created.revision)
    )
    found = job_store.get("business-1", "project-1", "job-1")

    assert updated.revision == 2
    assert found == updated
    assert found.job.checkpoint["step"] == "testing"
    assert found.job.checkpoint["completed"] == ("unit", "integration")


def test_stale_revision_cannot_overwrite_newer_job(job_store):
    created = job_store.create(make_job())
    stale = job_store.get("business-1", "project-1", "job-1")

    running = created.job.transition(
        ForgeJobStatus.RUNNING,
        created.job.created_at + timedelta(seconds=1),
    )
    job_store.update(type(created)(job=running, revision=created.revision))

    with pytest.raises(ForgeJobConflictError):
        job_store.update(stale)


def test_missing_job_lookup_returns_none(job_store):
    assert job_store.get("business-1", "project-1", "missing") is None


def test_wrong_database_type_is_rejected():
    with pytest.raises(TypeError):
        ForgeJobStore("database.sqlite3")


def test_claim_next_queued_atomically_starts_oldest_job(job_store):
    first = job_store.create(make_job(job_id="job-1"))
    job_store.create(make_job(
        job_id="job-2",
        created_at=first.job.created_at + timedelta(seconds=1),
        updated_at=first.job.updated_at + timedelta(seconds=1),
    ))
    claimed = job_store.claim_next_queued(
        first.job.created_at + timedelta(seconds=2),
        worker_id="worker-a",
        lease_expires_at=first.job.created_at + timedelta(minutes=2),
    )
    assert claimed is not None
    assert claimed.job.job_id == "job-1"
    assert claimed.job.status is ForgeJobStatus.RUNNING
    assert claimed.revision == 2
    assert job_store.get("business-1", "project-1", "job-1") == claimed


def test_claim_next_queued_does_not_claim_same_job_twice(job_store):
    created = job_store.create(make_job())
    claimed = job_store.claim_next_queued(
        created.job.created_at + timedelta(seconds=1),
        worker_id="worker-a",
        lease_expires_at=created.job.created_at + timedelta(minutes=2),
    )
    assert claimed is not None
    assert job_store.claim_next_queued(
        created.job.created_at + timedelta(seconds=2),
        worker_id="worker-b",
        lease_expires_at=created.job.created_at + timedelta(minutes=3),
    ) is None


def test_claim_next_queued_returns_none_when_queue_is_empty(job_store):
    assert job_store.claim_next_queued(
        datetime.now(timezone.utc),
        worker_id="worker-a",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
    ) is None


def test_claim_next_queued_requires_aware_datetime(job_store):
    with pytest.raises(ValueError, match="timezone-aware"):
        job_store.claim_next_queued(
            datetime(2026, 1, 1),
            worker_id="worker-a",
            lease_expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


def test_renew_lease_extends_expiry_and_updates_heartbeat(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    renewed_at = claimed_at + timedelta(seconds=30)
    new_expiry = renewed_at + timedelta(minutes=4)
    renewed = job_store.renew_lease(claimed, renewed_at, new_expiry)

    assert renewed.worker_id == "worker-a"
    assert renewed.lease_generation == claimed.lease_generation
    assert renewed.lease_expires_at == new_expiry
    assert renewed.job.heartbeat_at == renewed_at
    assert renewed.revision == claimed.revision + 1


def test_expired_worker_cannot_renew_lease(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    expired_at = claimed.lease_expires_at + timedelta(seconds=1)
    with pytest.raises(ForgeJobConflictError):
        job_store.renew_lease(
            claimed,
            expired_at,
            expired_at + timedelta(minutes=2),
        )


def test_replaced_worker_cannot_renew_lease(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    with job_store._database.transaction() as connection:
        connection.execute(
            """
            UPDATE forge_jobs
            SET lease_generation = lease_generation + 1
            WHERE business_id = ? AND project_id = ? AND job_id = ?
            """,
            ("business-1", "project-1", "job-1"),
        )

    renewed_at = claimed_at + timedelta(seconds=30)
    with pytest.raises(ForgeJobConflictError):
        job_store.renew_lease(
            claimed,
            renewed_at,
            renewed_at + timedelta(minutes=3),
        )


def test_recover_expired_lease_requeues_job_and_preserves_checkpoint(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    checkpointed_job = claimed.job.save_checkpoint(
        {"step": "testing", "completed": ["unit"]},
        claimed_at + timedelta(seconds=10),
    )
    checkpointed = job_store.update(
        type(claimed)(
            job=checkpointed_job,
            revision=claimed.revision,
            worker_id=claimed.worker_id,
            lease_expires_at=claimed.lease_expires_at,
            lease_generation=claimed.lease_generation,
        )
    )

    recovered_at = claimed.lease_expires_at + timedelta(seconds=1)
    recovered = job_store.recover_expired_lease(recovered_at)

    assert recovered is not None
    assert recovered.job.status is ForgeJobStatus.QUEUED
    assert recovered.job.checkpoint["step"] == "testing"
    assert recovered.job.checkpoint["completed"] == ("unit",)
    assert recovered.job.started_at is None
    assert recovered.job.heartbeat_at is None
    assert recovered.worker_id is None
    assert recovered.lease_expires_at is None
    assert recovered.lease_generation == checkpointed.lease_generation + 1
    assert recovered.revision == checkpointed.revision + 1


def test_recover_expired_lease_cancels_job_with_cancellation_requested(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    cancellation_at = claimed_at + timedelta(seconds=10)
    cancellation_job = claimed.job.request_cancellation(cancellation_at)
    cancellation_record = job_store.update(
        type(claimed)(
            job=cancellation_job,
            revision=claimed.revision,
            worker_id=claimed.worker_id,
            lease_expires_at=claimed.lease_expires_at,
            lease_generation=claimed.lease_generation,
        )
    )

    recovered_at = claimed.lease_expires_at + timedelta(seconds=1)
    recovered = job_store.recover_expired_lease(recovered_at)

    assert recovered is not None
    assert recovered.job.status is ForgeJobStatus.CANCELLED
    assert recovered.job.cancellation_requested is True
    assert recovered.job.completed_at == recovered_at
    assert recovered.worker_id is None
    assert recovered.lease_expires_at is None
    assert recovered.lease_generation == cancellation_record.lease_generation + 1


def test_recovered_lease_fences_out_previous_worker(job_store):
    created = job_store.create(make_job())
    claimed_at = created.job.created_at + timedelta(seconds=1)
    claimed = job_store.claim_next_queued(
        claimed_at,
        worker_id="worker-a",
        lease_expires_at=claimed_at + timedelta(minutes=2),
    )
    assert claimed is not None

    recovered_at = claimed.lease_expires_at + timedelta(seconds=1)
    recovered = job_store.recover_expired_lease(recovered_at)

    assert recovered is not None
    stale_job = claimed.job.heartbeat(recovered_at + timedelta(seconds=1))
    with pytest.raises(ForgeJobConflictError):
        job_store.update(
            type(claimed)(
                job=stale_job,
                revision=claimed.revision,
                worker_id=claimed.worker_id,
                lease_expires_at=claimed.lease_expires_at,
                lease_generation=claimed.lease_generation,
            )
        )


def make_spec(**overrides):
    values = {
        "business_id": "business-1",
        "project_id": "project-1",
        "job_id": "job-1",
        "instructions": "Review the implementation and identify defects.",
        "scope": ("app/forge", "tests"),
        "acceptance_criteria": ("All focused tests pass.",),
    }
    values.update(overrides)
    return ForgeTaskSpec(**values)


def test_create_with_spec_persists_job_and_immutable_spec(job_store):
    job = make_job()
    spec = make_spec()

    created = job_store.create_with_spec(job, spec)

    assert created.job == job
    assert created.revision == 1
    assert job_store.get_task_spec(
        "business-1", "project-1", "job-1"
    ) == spec


def test_create_with_spec_rejects_mismatched_identity_without_creating_job(
    job_store,
):
    spec = make_spec(business_id="business-2")

    with pytest.raises(ValueError, match="identity must match"):
        job_store.create_with_spec(make_job(), spec)

    assert job_store.get("business-1", "project-1", "job-1") is None


def test_create_with_spec_rolls_back_job_if_spec_insert_fails(job_store):
    database = job_store._database
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_forge_task_spec
            BEFORE INSERT ON forge_task_specs
            BEGIN
                SELECT RAISE(ABORT, 'simulated spec write failure');
            END
            """
        )

    with pytest.raises(Exception, match="simulated spec write failure"):
        job_store.create_with_spec(make_job(), make_spec())

    assert job_store.get("business-1", "project-1", "job-1") is None


def test_task_specs_are_isolated_between_businesses(job_store):
    first = make_spec(instructions="First business instructions.")
    second = make_spec(
        business_id="business-2",
        instructions="Second business instructions.",
    )

    job_store.create_with_spec(make_job(), first)
    job_store.create_with_spec(make_job(business_id="business-2"), second)

    assert job_store.get_task_spec(
        "business-1", "project-1", "job-1"
    ) == first
    assert job_store.get_task_spec(
        "business-2", "project-1", "job-1"
    ) == second


def test_legacy_job_without_spec_returns_none(job_store):
    job_store.create(make_job())

    assert job_store.get_task_spec(
        "business-1", "project-1", "job-1"
    ) is None


def test_tampered_task_spec_hash_is_rejected(job_store):
    job_store.create_with_spec(make_job(), make_spec())

    with job_store._database.transaction() as connection:
        connection.execute(
            """
            UPDATE forge_task_specs
            SET spec_sha256 = ?
            WHERE business_id = ? AND project_id = ? AND job_id = ?
            """,
            ("0" * 64, "business-1", "project-1", "job-1"),
        )

    with pytest.raises(ForgeTaskSpecIntegrityError):
        job_store.get_task_spec("business-1", "project-1", "job-1")




def test_new_worker_recovers_expired_job_and_executes_it(job_store):
    crashed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job_store.create_with_spec(
        make_job(created_at=crashed_at, updated_at=crashed_at),
        make_spec(),
    )

    stale_claim = job_store.claim_next_queued(
        at=crashed_at + timedelta(seconds=1),
        worker_id="crashed-worker",
        lease_expires_at=crashed_at + timedelta(seconds=11),
    )
    assert stale_claim is not None
    assert stale_claim.job.status is ForgeJobStatus.RUNNING
    assert stale_claim.lease_expires_at < datetime.now(timezone.utc)

    executed = []
    vaulted = []

    def executor(spec, context):
        executed.append(spec)
        return ForgeExecutionResult({"candidate": "recovered execution"})

    def vault(spec, result):
        vaulted.append((spec, result))
        return "forge-artifact://restart-recovery-test"

    restarted_worker = ForgeWorker(
        job_store=job_store,
        executor=executor,
        vault=vault,
        worker_id="restarted-worker",
        lease_seconds=30,
    )

    completed = restarted_worker.run_once()

    assert completed is not None
    assert completed.job.status is ForgeJobStatus.COMPLETED_VAULTED
    assert completed.worker_id == "restarted-worker"
    assert completed.job.checkpoint["artifact_reference"] == (
        "forge-artifact://restart-recovery-test"
    )
    assert executed == [make_spec()]
    assert len(vaulted) == 1
    assert vaulted[0][0] == make_spec()


def test_worker_automatically_renews_lease_during_execution(
    job_store, monkeypatch
):
    job_store.create_with_spec(make_job(), make_spec())

    renewals = []
    original_renew_lease = job_store.renew_lease

    def track_renewal(*args, **kwargs):
        renewed = original_renew_lease(*args, **kwargs)
        renewals.append(renewed)
        return renewed

    monkeypatch.setattr(job_store, "renew_lease", track_renewal)

    def slow_executor(spec, context):
        time.sleep(3.7)
        return ForgeExecutionResult(
            {"candidate": "generated during a long-running task"}
        )

    worker = ForgeWorker(
        job_store=job_store,
        executor=slow_executor,
        vault=lambda spec, result: "forge-artifact://heartbeat-test",
        worker_id="heartbeat-test-worker",
        lease_seconds=10,
    )

    completed = worker.run_once()

    assert renewals, "The worker did not automatically renew its lease."
    assert completed is not None
    assert completed.job.status == ForgeJobStatus.COMPLETED_VAULTED



def test_worker_stops_and_does_not_vault_when_cancelled(job_store):
    job_store.create_with_spec(make_job(), make_spec())
    vault_calls = []

    def executor(spec, context):
        current = job_store.get(
            spec.business_id, spec.project_id, spec.job_id
        )
        requested = current.job.request_cancellation(
            datetime.now(timezone.utc)
        )
        job_store.update(replace(current, job=requested))
        context.check_cancellation()
        raise AssertionError("Cancelled execution must not continue.")

    worker = ForgeWorker(
        job_store=job_store,
        executor=executor,
        vault=lambda spec, result: vault_calls.append(result),
        worker_id="cancellation-test-worker",
        lease_seconds=10,
    )

    cancelled = worker.run_once()

    assert cancelled is not None
    assert cancelled.job.status == ForgeJobStatus.CANCELLED
    assert vault_calls == []


def test_worker_does_not_vault_after_lease_is_replaced(job_store):
    job_store.create_with_spec(make_job(), make_spec())
    vault_calls = []

    def executor(spec, context):
        with job_store._database.transaction() as connection:
            connection.execute(
                """
                UPDATE forge_jobs
                SET worker_id = ?,
                    lease_generation = lease_generation + 1
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (
                    "replacement-worker",
                    spec.business_id,
                    spec.project_id,
                    spec.job_id,
                ),
            )

        # Allow the automatic heartbeat to encounter the new fencing token.
        time.sleep(3.7)
        return ForgeExecutionResult(
            {"candidate": "must not be vaulted by stale worker"}
        )

    worker = ForgeWorker(
        job_store=job_store,
        executor=executor,
        vault=lambda spec, result: vault_calls.append(result),
        worker_id="original-worker",
        lease_seconds=10,
    )

    current = worker.run_once()

    assert current is not None
    assert current.job.status == ForgeJobStatus.RUNNING
    assert current.worker_id == "replacement-worker"
    assert vault_calls == []


def test_forge_worker_runner_restarts_after_stop(job_store, monkeypatch):
    worker = ForgeWorker(
        job_store=job_store,
        executor=lambda spec, context: ForgeExecutionResult({}),
        vault=lambda spec, result: "forge-artifact://runner-test",
        worker_id="runner-restart-test",
        lease_seconds=10,
    )
    first_run = threading.Event()
    second_run = threading.Event()
    calls = 0

    def run_once():
        nonlocal calls
        calls += 1
        (first_run if calls == 1 else second_run).set()

    monkeypatch.setattr(worker, "run_once", run_once)
    runner = ForgeWorkerRunner(worker, poll_interval=0.01)

    assert runner.start() is runner
    assert first_run.wait(1)
    assert runner.stop(timeout=1)
    assert not runner.is_running
    assert runner.start() is runner
    assert second_run.wait(1)
    assert runner.stop(timeout=1)


def test_forge_worker_runner_continues_after_iteration_error(job_store, monkeypatch):
    worker = ForgeWorker(
        job_store=job_store,
        executor=lambda spec, context: ForgeExecutionResult({}),
        vault=lambda spec, result: "forge-artifact://runner-test",
        worker_id="runner-recovery-test",
        lease_seconds=10,
    )
    recovered = threading.Event()
    calls = 0

    def run_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated iteration failure")
        recovered.set()

    monkeypatch.setattr(worker, "run_once", run_once)
    runner = ForgeWorkerRunner(worker, poll_interval=0.01)
    runner.start()
    assert recovered.wait(1)
    assert calls >= 2
    assert runner.stop(timeout=1)


def test_forge_worker_runner_rejects_invalid_stop_timeouts(job_store):
    worker = ForgeWorker(
        job_store=job_store,
        executor=lambda spec, context: ForgeExecutionResult({}),
        vault=lambda spec, result: "forge-artifact://runner-test",
        worker_id="runner-timeout-test",
        lease_seconds=10,
    )
    runner = ForgeWorkerRunner(worker)

    for invalid in (float("nan"), float("inf"), -1):
        with pytest.raises(ValueError):
            runner.stop(timeout=invalid)

    for invalid in (True, "1"):
        with pytest.raises(TypeError):
            runner.stop(timeout=invalid)


def test_forge_worker_runner_survives_system_exit(job_store, monkeypatch):
    worker = ForgeWorker(
        job_store=job_store,
        executor=lambda spec, context: ForgeExecutionResult({}),
        vault=lambda spec, result: "forge-artifact://runner-test",
        worker_id="runner-system-exit-test",
        lease_seconds=10,
    )
    recovered = threading.Event()
    calls = 0

    def run_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemExit("simulated worker-thread exit")
        recovered.set()

    monkeypatch.setattr(worker, "run_once", run_once)
    runner = ForgeWorkerRunner(worker, poll_interval=0.01)

    runner.start()
    assert recovered.wait(1)
    assert calls >= 2
    assert runner.stop(timeout=1)
