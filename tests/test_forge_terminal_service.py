from datetime import datetime, timezone

import pytest

from app.forge.artifact_store import ForgeArtifactStore
from app.forge.artifact_vault import ForgeArtifactVault
from app.forge.job import ForgeJob
from app.forge.job_store import ForgeJobStore
from app.forge.project_store import ForgeProjectStore
from app.forge.python_executor import ForgePythonCandidateExecutor
from app.forge.terminal_service import (
    ForgeTerminalService,
    ForgeTerminalSessionError,
)
from app.forge.task_spec import ForgeTaskSpec
from app.forge.toolchains import build_toolchain_plan
from app.forge.verification import build_candidate_verification_report
from app.forge.worker import ForgeExecutionResult, ForgeWorker
from app.persistence.database import SQLiteDatabase


@pytest.fixture
def forge_environment(tmp_path):
    database = SQLiteDatabase(tmp_path / "forge.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("business-1", "Test Business", "Owner", "Amination", "male"),
        )

    projects = ForgeProjectStore(database)
    projects.create("business-1", "project-1", "Terminal Test")

    jobs = ForgeJobStore(database)
    artifacts = ForgeArtifactStore(database, tmp_path / "artifacts")
    vault = ForgeArtifactVault(artifacts)

    spec = ForgeTaskSpec(
        business_id="business-1",
        project_id="project-1",
        job_id="job-1",
        instructions="Create a small Python candidate.",
        scope=("src/main.py",),
        acceptance_criteria=("The source file exists.",),
    )

    job = ForgeJob(
        job_id="job-1",
        business_id="business-1",
        project_id="project-1",
        job_type="code_review",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    jobs.create_with_spec(job, spec)

    files = {"src/main.py": "print('original')\n"}
    checks = ForgePythonCandidateExecutor._static_checks(files)

    candidate = {
        "format": "amination-forge-candidate-v1",
        "business_id": spec.business_id,
        "project_id": spec.project_id,
        "job_id": spec.job_id,
        "language": spec.language,
        "toolchain_plan": build_toolchain_plan(spec.language),
        "files": files,
        "checks": checks,
        "verification": build_candidate_verification_report(files, checks),
        "candidate_revision": 1,
        "execution_policy": {
            "generated_code_executed": False,
            "live_repository_modified": False,
            "shell_commands_invoked": False,
        },
    }

    worker = ForgeWorker(
        job_store=jobs,
        executor=lambda task, context: ForgeExecutionResult(candidate),
        vault=vault,
        worker_id="terminal-test-worker",
        lease_seconds=30,
    )
    completed = worker.run_once()
    assert completed is not None
    assert completed.job.status.value == "completed_vaulted"

    return {
        "jobs": jobs,
        "artifacts": artifacts,
        "vault": vault,
        "spec": spec,
        "root": tmp_path / "sessions",
    }


def make_service(environment, name):
    return ForgeTerminalService(
        job_store=environment["jobs"],
        artifact_store=environment["artifacts"],
        artifact_vault=environment["vault"],
        workspace_root=environment["root"] / name,
    )


def test_saved_terminal_revision_survives_service_restart(forge_environment):
    first_service = make_service(forge_environment, "first")
    opened = first_service.open_session("business-1", "project-1", "job-1")

    assert opened["reused"] is False

    result = first_service.execute(
        "business-1",
        "project-1",
        "job-1",
        'write src/main.py "print(42)"',
    )
    assert result["ok"] is True

    saved = first_service.save_session("business-1", "project-1", "job-1")
    assert saved["verification_status"] == "pass"
    assert saved["execution_enabled"] is False
    assert saved["live_repository_modified"] is False

    current = forge_environment["jobs"].get(
        "business-1", "project-1", "job-1"
    )
    assert current.job.checkpoint["artifact_reference"] == saved["artifact_reference"]
    assert current.job.checkpoint["candidate_revision"] == 2

    first_service.close_all()

    # A new service instance must recover the latest durable artifact pointer.
    restarted_service = make_service(forge_environment, "restarted")
    reopened = restarted_service.open_session(
        "business-1", "project-1", "job-1"
    )

    assert reopened["artifact_reference"] == saved["artifact_reference"]

    contents = restarted_service.execute(
        "business-1", "project-1", "job-1", "cat src/main.py"
    )
    assert contents["ok"] is True
    assert "print(42)" in contents["output"]

    restarted_service.close_all()


def test_stale_terminal_session_cannot_overwrite_newer_revision(
    forge_environment,
):
    first_service = make_service(forge_environment, "writer-one")
    stale_service = make_service(forge_environment, "writer-two")

    first_service.open_session("business-1", "project-1", "job-1")
    stale_service.open_session("business-1", "project-1", "job-1")

    first_service.execute(
        "business-1",
        "project-1",
        "job-1",
        'write src/main.py "print(100)"',
    )
    first_save = first_service.save_session(
        "business-1", "project-1", "job-1"
    )

    # A stale session must be rejected before it can execute a command.
    with pytest.raises(ForgeTerminalSessionError, match="stale"):
        stale_service.execute(
            "business-1",
            "project-1",
            "job-1",
            'write src/main.py "print(200)"',
        )

    # It must also be unable to save or replace the newer revision.
    with pytest.raises(ForgeTerminalSessionError, match="stale"):
        stale_service.save_session(
            "business-1", "project-1", "job-1"
        )

    current = forge_environment["jobs"].get(
        "business-1", "project-1", "job-1"
    )
    assert current.job.checkpoint["artifact_reference"] == (
        first_save["artifact_reference"]
    )
    assert current.job.checkpoint["candidate_revision"] == 2

    first_service.close_all()
    stale_service.close_all()
