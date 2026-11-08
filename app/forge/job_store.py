"""Tenant-scoped persistent storage for Forge jobs."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.forge.job import ForgeJob, ForgeJobStatus
from app.forge.task_spec import ForgeTaskSpec
from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)


class ForgeJobAlreadyExistsError(ValueError):
    """Raised when a job ID already exists within its project."""


class ForgeJobNotFoundError(LookupError):
    """Raised when a requested job does not exist."""


class ForgeJobConflictError(RuntimeError):
    """Raised when a job was changed by another process."""


class ForgeTaskSpecIntegrityError(RuntimeError):
    """Raised when a stored Forge task specification fails integrity checks."""


@dataclass(frozen=True)
class ForgeJobRecord:
    """A job together with its persistence revision."""

    job: ForgeJob
    revision: int
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    lease_generation: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.job, ForgeJob):
            raise TypeError("job must be a ForgeJob.")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("revision must be a positive integer.")

        if self.worker_id is not None:
            ForgeJob._validate_text(
                "worker_id", self.worker_id, ForgeJob.MAX_ID_LENGTH
            )
            if self.worker_id != self.worker_id.strip():
                raise ValueError("worker_id must not have outer whitespace.")
        if self.lease_expires_at is not None:
            if (
                not isinstance(self.lease_expires_at, datetime)
                or self.lease_expires_at.tzinfo is None
                or self.lease_expires_at.utcoffset() is None
            ):
                raise ValueError("lease_expires_at must be timezone-aware.")
        if (
            isinstance(self.lease_generation, bool)
            or not isinstance(self.lease_generation, int)
            or self.lease_generation < 0
        ):
            raise ValueError("lease_generation must be a non-negative integer.")



class ForgeJobStore:
    """Persist Forge jobs with tenant isolation and revision checks."""

    def __init__(self, database: SQLiteDatabase):
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")
        self._database = database

    def create(self, job: ForgeJob) -> ForgeJobRecord:
        if not isinstance(job, ForgeJob):
            raise TypeError("job must be a ForgeJob.")

        with self._database.transaction() as connection:
            project = connection.execute(
                """
                SELECT 1 FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (job.business_id, job.project_id),
            ).fetchone()

            if project is None:
                raise ValueError("An existing project is required.")

            existing = connection.execute(
                """
                SELECT 1 FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (job.business_id, job.project_id, job.job_id),
            ).fetchone()

            if existing is not None:
                raise ForgeJobAlreadyExistsError(
                    "A Forge job with this ID already exists."
                )

            connection.execute(
                """
                INSERT INTO forge_jobs (
                    business_id, project_id, job_id, job_type,
                    status, phase, progress, created_at, updated_at,
                    heartbeat_at, started_at, completed_at,
                    cancellation_requested, checkpoint_json,
                    error_code, error_message, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                self._job_values(job),
            )

        return ForgeJobRecord(job=job, revision=1)

    def create_with_spec(
        self,
        job: ForgeJob,
        spec: ForgeTaskSpec,
    ) -> ForgeJobRecord:
        """Atomically create a Forge job and its immutable task specification."""
        if not isinstance(job, ForgeJob):
            raise TypeError("job must be a ForgeJob.")
        if not isinstance(spec, ForgeTaskSpec):
            raise TypeError("spec must be a ForgeTaskSpec.")

        expected_identity = (
            job.business_id,
            job.project_id,
            job.job_id,
        )
        spec_identity = (
            spec.business_id,
            spec.project_id,
            spec.job_id,
        )
        if spec_identity != expected_identity:
            raise ValueError("Task specification identity must match its job.")

        with self._database.transaction() as connection:
            project = connection.execute(
                """
                SELECT 1 FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (job.business_id, job.project_id),
            ).fetchone()
            if project is None:
                raise ValueError("An existing project is required.")

            existing = connection.execute(
                """
                SELECT 1 FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                expected_identity,
            ).fetchone()
            if existing is not None:
                raise ForgeJobAlreadyExistsError(
                    "A Forge job with this ID already exists."
                )

            connection.execute(
                """
                INSERT INTO forge_jobs (
                    business_id, project_id, job_id, job_type,
                    status, phase, progress, created_at, updated_at,
                    heartbeat_at, started_at, completed_at,
                    cancellation_requested, checkpoint_json,
                    error_code, error_message, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                self._job_values(job),
            )
            connection.execute(
                """
                INSERT INTO forge_task_specs (
                    business_id, project_id, job_id,
                    spec_json, spec_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    spec.business_id,
                    spec.project_id,
                    spec.job_id,
                    spec.to_json(),
                    spec.sha256,
                    datetime_to_storage(job.created_at),
                ),
            )

        return ForgeJobRecord(job=job, revision=1)

    def get_task_spec(
        self,
        business_id: str,
        project_id: str,
        job_id: str,
    ) -> ForgeTaskSpec | None:
        """Load a task specification and verify its stored identity and hash."""
        self._validate_scope(business_id, project_id, job_id)

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT spec_json, spec_sha256
                FROM forge_task_specs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (business_id, project_id, job_id),
            ).fetchone()

        if row is None:
            return None

        try:
            spec = ForgeTaskSpec.from_json(row["spec_json"])
            stored_hash = row["spec_sha256"]
            if (
                not isinstance(stored_hash, str)
                or len(stored_hash) != 64
                or stored_hash != stored_hash.lower()
                or any(char not in "0123456789abcdef" for char in stored_hash)
                or stored_hash != spec.sha256
            ):
                raise ValueError("Stored task specification hash is invalid.")

            if (
                spec.business_id,
                spec.project_id,
                spec.job_id,
            ) != (business_id, project_id, job_id):
                raise ValueError("Stored task specification identity is invalid.")

            return spec
        except (KeyError, TypeError, ValueError) as exc:
            raise ForgeTaskSpecIntegrityError(
                "Stored Forge task specification failed integrity checks."
            ) from exc

    def get(
        self,
        business_id: str,
        project_id: str,
        job_id: str,
    ) -> ForgeJobRecord | None:
        self._validate_scope(business_id, project_id, job_id)

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (business_id, project_id, job_id),
            ).fetchone()

        return None if row is None else self._from_row(row)

    def list_for_project(
        self,
        business_id: str,
        project_id: str,
    ) -> list[ForgeJobRecord]:
        self._validate_scope(business_id, project_id)

        with self._database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE business_id = ? AND project_id = ?
                ORDER BY created_at DESC, job_id ASC
                """,
                (business_id, project_id),
            ).fetchall()

        return [self._from_row(row) for row in rows]

    def claim_next_queued(
        self,
        at: datetime,
        worker_id: str,
        lease_expires_at: datetime,
    ) -> ForgeJobRecord | None:
        """Atomically claim the oldest queued job with a worker lease."""
        if not isinstance(at, datetime):
            raise TypeError("at must be a datetime.")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware.")
        ForgeJob._validate_text("worker_id", worker_id, ForgeJob.MAX_ID_LENGTH)
        if worker_id != worker_id.strip():
            raise ValueError("worker_id must not have outer whitespace.")
        if not isinstance(lease_expires_at, datetime):
            raise TypeError("lease_expires_at must be a datetime.")
        if lease_expires_at.tzinfo is None or lease_expires_at.utcoffset() is None:
            raise ValueError("lease_expires_at must be timezone-aware.")
        if lease_expires_at <= at:
            raise ValueError("lease_expires_at must be later than at.")

        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE status = ?
                ORDER BY created_at ASC, business_id ASC, project_id ASC, job_id ASC
                LIMIT 1
                """,
                (ForgeJobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                return None

            record = self._from_row(row)
            running = record.job.transition(ForgeJobStatus.RUNNING, at)
            cursor = connection.execute(
                """
                UPDATE forge_jobs
                SET status = ?, phase = ?, updated_at = ?, started_at = ?,
                    worker_id = ?, lease_expires_at = ?,
                    lease_generation = lease_generation + 1,
                    revision = revision + 1
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                  AND revision = ? AND status = ?
                """,
                (
                    running.status.value,
                    running.phase,
                    datetime_to_storage(running.updated_at),
                    self._optional_datetime(running.started_at),
                    worker_id,
                    datetime_to_storage(lease_expires_at),
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                    record.revision,
                    ForgeJobStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ForgeJobConflictError("This job was claimed by another worker.")

            claimed_row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (running.business_id, running.project_id, running.job_id),
            ).fetchone()
            if claimed_row is None:
                raise RuntimeError("Claimed Forge job could not be reloaded.")
            return self._from_row(claimed_row)

    def recover_expired_lease(self, at: datetime) -> ForgeJobRecord | None:
        """Recover one expired worker lease and fence out its old worker."""
        if not isinstance(at, datetime):
            raise TypeError("at must be a datetime.")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware.")

        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE status = ? AND worker_id IS NOT NULL
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                ORDER BY lease_expires_at ASC, created_at ASC,
                         business_id ASC, project_id ASC, job_id ASC
                LIMIT 1
                """,
                (
                    ForgeJobStatus.RUNNING.value,
                    datetime_to_storage(at),
                ),
            ).fetchone()

            if row is None:
                return None

            record = self._from_row(row)
            if record.job.cancellation_requested:
                recovered = record.job.transition(
                    ForgeJobStatus.CANCELLED,
                    at,
                )
            else:
                recovered = record.job

            cancelled = recovered.status is ForgeJobStatus.CANCELLED
            cursor = connection.execute(
                """
                UPDATE forge_jobs
                SET status = ?, phase = ?, updated_at = ?,
                    heartbeat_at = ?, started_at = ?, completed_at = ?,
                    worker_id = NULL, lease_expires_at = NULL,
                    lease_generation = lease_generation + 1,
                    revision = revision + 1
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                  AND revision = ? AND lease_generation = ?
                  AND worker_id = ? AND lease_expires_at = ?
                  AND status = ?
                """,
                (
                    recovered.status.value if cancelled else ForgeJobStatus.QUEUED.value,
                    recovered.phase if cancelled else "queued",
                    datetime_to_storage(at),
                    self._optional_datetime(recovered.heartbeat_at) if cancelled else None,
                    self._optional_datetime(recovered.started_at) if cancelled else None,
                    self._optional_datetime(recovered.completed_at) if cancelled else None,
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                    record.revision,
                    record.lease_generation,
                    record.worker_id,
                    datetime_to_storage(record.lease_expires_at),
                    ForgeJobStatus.RUNNING.value,
                ),
            )

            if cursor.rowcount != 1:
                raise ForgeJobConflictError(
                    "The expired Forge job changed during recovery."
                )

            recovered_row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                ),
            ).fetchone()

            if recovered_row is None:
                raise RuntimeError("Recovered Forge job could not be reloaded.")

            return self._from_row(recovered_row)

    def renew_lease(
        self,
        record: ForgeJobRecord,
        at: datetime,
        lease_expires_at: datetime,
    ) -> ForgeJobRecord:
        """Renew a running job lease using its current fencing token."""
        if not isinstance(record, ForgeJobRecord):
            raise TypeError("record must be a ForgeJobRecord.")
        for name, value in (
            ("at", at),
            ("lease_expires_at", lease_expires_at),
        ):
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must be timezone-aware.")

        if record.worker_id is None or record.lease_expires_at is None:
            raise ValueError("A worker lease is required to renew it.")
        if lease_expires_at <= at:
            raise ValueError("The renewed lease must expire after at.")
        if lease_expires_at <= record.lease_expires_at:
            raise ValueError("The renewed lease must extend the current expiry.")

        job = record.job.heartbeat(at)

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE forge_jobs
                SET heartbeat_at = ?, updated_at = ?, lease_expires_at = ?,
                    revision = revision + 1
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                  AND revision = ? AND lease_generation = ?
                  AND worker_id = ? AND lease_expires_at > ?
                  AND status = ?
                """,
                (
                    self._optional_datetime(job.heartbeat_at),
                    datetime_to_storage(job.updated_at),
                    datetime_to_storage(lease_expires_at),
                    job.business_id,
                    job.project_id,
                    job.job_id,
                    record.revision,
                    record.lease_generation,
                    record.worker_id,
                    datetime_to_storage(at),
                    ForgeJobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ForgeJobConflictError(
                    "The worker lease expired or was replaced before renewal."
                )

            renewed_row = connection.execute(
                """
                SELECT * FROM forge_jobs
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                """,
                (job.business_id, job.project_id, job.job_id),
            ).fetchone()

            if renewed_row is None:
                raise RuntimeError("Renewed Forge job could not be reloaded.")

            return self._from_row(renewed_row)

    def update(self, record: ForgeJobRecord) -> ForgeJobRecord:
        if not isinstance(record, ForgeJobRecord):
            raise TypeError("record must be a ForgeJobRecord.")

        job = record.job

        with self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE forge_jobs
                SET job_type = ?, status = ?, phase = ?, progress = ?,
                    updated_at = ?, heartbeat_at = ?, started_at = ?,
                    completed_at = ?, cancellation_requested = ?,
                    checkpoint_json = ?, error_code = ?, error_message = ?,
                    revision = revision + 1
                WHERE business_id = ? AND project_id = ? AND job_id = ?
                  AND revision = ?
                  AND lease_generation = ?
                  AND worker_id IS ?
                  AND (worker_id IS NULL OR lease_expires_at > ?)
                """,
                (
                    job.job_type,
                    job.status.value,
                    job.phase,
                    job.progress,
                    datetime_to_storage(job.updated_at),
                    self._optional_datetime(job.heartbeat_at),
                    self._optional_datetime(job.started_at),
                    self._optional_datetime(job.completed_at),
                    int(job.cancellation_requested),
                    self._checkpoint_to_storage(job.checkpoint),
                    job.error_code,
                    job.error_message,
                    job.business_id,
                    job.project_id,
                    job.job_id,
                    record.revision,
                    record.lease_generation,
                    record.worker_id,
                    datetime_to_storage(job.updated_at),
                ),
            )

            if cursor.rowcount == 0:
                existing = connection.execute(
                    """
                    SELECT 1 FROM forge_jobs
                    WHERE business_id = ? AND project_id = ? AND job_id = ?
                    """,
                    (job.business_id, job.project_id, job.job_id),
                ).fetchone()

                if existing is None:
                    raise ForgeJobNotFoundError("Forge job not found.")

                raise ForgeJobConflictError(
                    "This job has changed since it was last retrieved."
                )

        return ForgeJobRecord(
            job=job,
            revision=record.revision + 1,
            worker_id=record.worker_id,
            lease_expires_at=record.lease_expires_at,
            lease_generation=record.lease_generation,
        )

    @staticmethod
    def _validate_scope(*values: str) -> None:
        for value in values:
            ForgeJob._validate_text("identifier", value, ForgeJob.MAX_ID_LENGTH)
            if value != value.strip():
                raise ValueError("Identifiers must not contain outer whitespace.")

    @staticmethod
    def _optional_datetime(value) -> str | None:
        return None if value is None else datetime_to_storage(value)

    @classmethod
    def _checkpoint_to_storage(cls, checkpoint: Mapping[str, Any] | None):
        if checkpoint is None:
            return None

        def thaw(value):
            if isinstance(value, Mapping):
                return {key: thaw(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [thaw(item) for item in value]
            return value

        return json.dumps(
            thaw(checkpoint),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _job_values(job: ForgeJob) -> tuple:
        return (
            job.business_id,
            job.project_id,
            job.job_id,
            job.job_type,
            job.status.value,
            job.phase,
            job.progress,
            datetime_to_storage(job.created_at),
            datetime_to_storage(job.updated_at),
            ForgeJobStore._optional_datetime(job.heartbeat_at),
            ForgeJobStore._optional_datetime(job.started_at),
            ForgeJobStore._optional_datetime(job.completed_at),
            int(job.cancellation_requested),
            ForgeJobStore._checkpoint_to_storage(job.checkpoint),
            job.error_code,
            job.error_message,
        )

    @staticmethod
    def _from_row(row) -> ForgeJobRecord:
        try:
            checkpoint_json = row["checkpoint_json"]
            checkpoint = (
                None if checkpoint_json is None else json.loads(checkpoint_json)
            )

            cancellation_flag = row["cancellation_requested"]
            if (
                isinstance(cancellation_flag, bool)
                or not isinstance(cancellation_flag, int)
                or cancellation_flag not in (0, 1)
            ):
                raise ValueError("Stored cancellation flag is invalid.")

            job = ForgeJob(
                job_id=row["job_id"],
                business_id=row["business_id"],
                project_id=row["project_id"],
                job_type=row["job_type"],
                status=ForgeJobStatus(row["status"]),
                phase=row["phase"],
                progress=row["progress"],
                created_at=datetime_from_storage(row["created_at"]),
                updated_at=datetime_from_storage(row["updated_at"]),
                heartbeat_at=(
                    None if row["heartbeat_at"] is None
                    else datetime_from_storage(row["heartbeat_at"])
                ),
                started_at=(
                    None if row["started_at"] is None
                    else datetime_from_storage(row["started_at"])
                ),
                completed_at=(
                    None if row["completed_at"] is None
                    else datetime_from_storage(row["completed_at"])
                ),
                cancellation_requested=bool(cancellation_flag),
                checkpoint=checkpoint,
                error_code=row["error_code"],
                error_message=row["error_message"],
            )
            return ForgeJobRecord(
                job=job,
                revision=row["revision"],
                worker_id=row["worker_id"],
                lease_expires_at=(
                    None if row["lease_expires_at"] is None
                    else datetime_from_storage(row["lease_expires_at"])
                ),
                lease_generation=row["lease_generation"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Stored Forge job data is invalid.") from exc
