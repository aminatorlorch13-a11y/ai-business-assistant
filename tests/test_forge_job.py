from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.forge.job import ForgeJob, ForgeJobStatus


NOW = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def make_job(**overrides):
    values = {
        "job_id": "job-1",
        "business_id": "business-1",
        "project_id": "project-1",
        "job_type": "code_review",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ForgeJob(**values)


def test_new_job_starts_queued():
    job = make_job()

    assert job.status is ForgeJobStatus.QUEUED
    assert job.progress == 0
    assert job.phase == "queued"
    assert job.started_at is None
    assert job.completed_at is None


def test_job_is_immutable():
    job = make_job()

    with pytest.raises(FrozenInstanceError):
        job.progress = 20


def test_queued_job_can_start():
    job = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )

    assert job.status is ForgeJobStatus.RUNNING
    assert job.started_at == NOW + timedelta(seconds=1)


def test_running_job_can_update_progress_and_heartbeat():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    updated = running.update_progress(
        35, "analysing_source", NOW + timedelta(seconds=2)
    )
    updated = updated.heartbeat(NOW + timedelta(seconds=3))

    assert updated.progress == 35
    assert updated.phase == "analysing_source"
    assert updated.heartbeat_at == NOW + timedelta(seconds=3)


def test_progress_cannot_move_backwards():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    ).update_progress(40, "testing", NOW + timedelta(seconds=2))

    with pytest.raises(ValueError, match="backwards"):
        running.update_progress(20, "testing", NOW + timedelta(seconds=3))


def test_running_job_can_save_checkpoint():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    updated = running.save_checkpoint(
        {"stage": "tests", "completed": ["unit", "static"]},
        NOW + timedelta(seconds=2),
    )

    assert updated.checkpoint["stage"] == "tests"
    assert updated.checkpoint["completed"] == ("unit", "static")


def test_checkpoint_rejects_secret_fields():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="forbidden"):
        running.save_checkpoint(
            {"api_key": "do-not-store"},
            NOW + timedelta(seconds=2),
        )


def test_running_job_requests_cancellation_without_claiming_it_stopped():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    requested = running.request_cancellation(NOW + timedelta(seconds=2))

    assert requested.status is ForgeJobStatus.RUNNING
    assert requested.cancellation_requested is True


def test_queued_job_can_be_cancelled_immediately():
    cancelled = make_job().request_cancellation(NOW + timedelta(seconds=1))

    assert cancelled.status is ForgeJobStatus.CANCELLED
    assert cancelled.completed_at == NOW + timedelta(seconds=1)


def test_successful_job_must_be_vaulted_before_locked():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    vaulted = running.transition(
        ForgeJobStatus.COMPLETED_VAULTED, NOW + timedelta(seconds=2)
    )
    locked = vaulted.transition(
        ForgeJobStatus.COMPLETED_VAULTED_LOCKED, NOW + timedelta(seconds=3)
    )

    assert vaulted.progress == 100
    assert locked.status is ForgeJobStatus.COMPLETED_VAULTED_LOCKED


def test_failed_job_requires_error_code():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="error_code"):
        running.transition(ForgeJobStatus.FAILED, NOW + timedelta(seconds=2))


def test_failed_job_records_error():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    failed = running.transition(
        ForgeJobStatus.FAILED,
        NOW + timedelta(seconds=2),
        error_code="BUILD_FAILED",
        error_message="Build command returned a non-zero exit code.",
    )

    assert failed.status is ForgeJobStatus.FAILED
    assert failed.error_code == "BUILD_FAILED"


def test_finished_job_cannot_be_restarted():
    cancelled = make_job().request_cancellation(NOW + timedelta(seconds=1))

    with pytest.raises(ValueError, match="not allowed"):
        cancelled.transition(
            ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
        )


def test_running_job_cannot_be_marked_complete_without_vaulting():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="not allowed"):
        running.transition(ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
                           NOW + timedelta(seconds=2))


def test_job_rejects_naive_datetimes():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_job(created_at=datetime(2026, 11, 3, 9, 0))


def test_job_rejects_invalid_progress():
    with pytest.raises(ValueError, match="between 0 and 100"):
        make_job(progress=101)


def test_checkpoint_is_deeply_immutable():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )
    updated = running.save_checkpoint(
        {
            "stage": "tests",
            "completed": ["unit"],
            "details": {"count": 1},
        },
        NOW + timedelta(seconds=2),
    )

    with pytest.raises(TypeError):
        updated.checkpoint["stage"] = "changed"

    with pytest.raises(TypeError):
        updated.checkpoint["details"]["count"] = 2

    with pytest.raises(AttributeError):
        updated.checkpoint["completed"].append("integration")

    assert updated.checkpoint["completed"] == ("unit",)


def test_heartbeat_cannot_move_job_time_backwards():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
    )

    with pytest.raises(ValueError, match="backwards"):
        running.heartbeat(NOW + timedelta(seconds=1))


def test_checkpoint_cannot_move_job_time_backwards():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
    )

    with pytest.raises(ValueError, match="backwards"):
        running.save_checkpoint(
            {"stage": "tests"},
            NOW + timedelta(seconds=1),
        )


def test_progress_update_cannot_move_job_time_backwards():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
    )

    with pytest.raises(ValueError, match="backwards"):
        running.update_progress(
            10, "testing", NOW + timedelta(seconds=1)
        )


def test_cancellation_request_cannot_move_job_time_backwards():
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
    )

    with pytest.raises(ValueError, match="backwards"):
        running.request_cancellation(NOW + timedelta(seconds=1))


def test_job_timestamps_cannot_exceed_updated_at():
    import dataclasses

    job = make_job()
    future = NOW + timedelta(seconds=1)

    for field in ("started_at", "heartbeat_at", "completed_at"):
        with pytest.raises(ValueError, match="later than updated_at"):
            dataclasses.replace(job, **{field: future})


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_checkpoint_rejects_non_finite_numbers(number):
    running = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=1)
    )

    with pytest.raises(ValueError, match="finite"):
        running.save_checkpoint(
            {"nested": {"measurement": number}},
            NOW + timedelta(seconds=2),
        )


def test_completed_at_cannot_precede_started_at():
    import dataclasses

    job = make_job().transition(
        ForgeJobStatus.RUNNING, NOW + timedelta(seconds=2)
    )

    with pytest.raises(ValueError, match="completed_at cannot precede started_at"):
        dataclasses.replace(
            job,
            status=ForgeJobStatus.FAILED,
            phase="failed",
            error_code="TEST_FAILURE",
            completed_at=NOW + timedelta(seconds=1),
        )
