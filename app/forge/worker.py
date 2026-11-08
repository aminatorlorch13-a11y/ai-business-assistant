from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
import uuid
import threading

from app.forge.job import ForgeJob, ForgeJobStatus
from app.forge.job_store import ForgeJobRecord, ForgeJobStore
from app.forge.task_spec import ForgeTaskSpec


class ForgeCancellationRequested(Exception):
    """Raised when a running Forge job receives a cancellation request."""


@dataclass(frozen=True)
class ForgeExecutionResult:
    """Output produced by an execution adapter before it enters the vault."""

    candidate: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Mapping) or not self.candidate:
            raise ValueError("Execution must return a non-empty candidate mapping.")


class ForgeLeaseLost(Exception):
    """Raised when this worker no longer owns the job lease."""


class ForgeExecutionContext:
    """Fenced progress, checkpoint, heartbeat and cancellation controls."""

    def __init__(
        self,
        store: ForgeJobStore,
        record: ForgeJobRecord,
        lease_seconds: int,
    ) -> None:
        self._store = store
        self._record = record
        self._lease_seconds = lease_seconds
        self._lock = threading.RLock()
        self._lease_error: Exception | None = None

    def _ensure_lease(self) -> None:
        if self._lease_error is not None:
            raise ForgeLeaseLost(
                "Forge worker lost ownership of this job lease."
            ) from self._lease_error

    @property
    def lease_lost(self) -> bool:
        with self._lock:
            return self._lease_error is not None

    @property
    def job(self) -> ForgeJob:
        with self._lock:
            self._ensure_lease()
            return self._record.job

    def check_lease(self) -> None:
        with self._lock:
            self._ensure_lease()

    def report_progress(self, progress: int, phase: str) -> None:
        with self._lock:
            self._ensure_lease()
            now = datetime.now(timezone.utc)
            self._record = self._store.update(
                replace(
                    self._record,
                    job=self._record.job.update_progress(progress, phase, now),
                )
            )

    def save_checkpoint(self, checkpoint: Mapping[str, Any]) -> None:
        with self._lock:
            self._ensure_lease()
            now = datetime.now(timezone.utc)
            self._record = self._store.update(
                replace(
                    self._record,
                    job=self._record.job.save_checkpoint(checkpoint, now),
                )
            )

    def heartbeat(self) -> None:
        with self._lock:
            self._ensure_lease()
            now = datetime.now(timezone.utc)
            try:
                self._record = self._store.renew_lease(
                    self._record,
                    now,
                    now + timedelta(seconds=self._lease_seconds),
                )
            except Exception as exc:
                self._lease_error = exc
                raise ForgeLeaseLost(
                    "Forge worker could not renew its job lease."
                ) from exc

    def check_cancellation(self) -> None:
        with self._lock:
            self._ensure_lease()
            current = self._store.get(
                self._record.job.business_id,
                self._record.job.project_id,
                self._record.job.job_id,
            )
            if current is None:
                raise RuntimeError("Forge job disappeared during execution.")
            if current.job.cancellation_requested:
                self._record = current
                raise ForgeCancellationRequested(
                    "The job was cancelled by an authorized request."
                )

    def persist_cancellation(self) -> ForgeJobRecord:
        with self._lock:
            self._ensure_lease()
            now = datetime.now(timezone.utc)
            self._record = self._store.update(
                replace(
                    self._record,
                    job=self._record.job.transition(
                        ForgeJobStatus.CANCELLED, now
                    ),
                )
            )
            return self._record


Executor = Callable[
    [ForgeTaskSpec, ForgeExecutionContext],
    ForgeExecutionResult,
]
Vault = Callable[
    [ForgeTaskSpec, ForgeExecutionResult],
    str,
]


class ForgeWorker:
    """
    Claims and executes one queued Forge job.

    Execution and vaulting are injected adapters. This worker never executes
    arbitrary shell commands or writes directly into a live repository.
    """

    def __init__(
        self,
        *,
        job_store: ForgeJobStore,
        executor: Executor,
        vault: Vault,
        worker_id: str | None = None,
        lease_seconds: int = 60,
    ) -> None:
        if not isinstance(job_store, ForgeJobStore):
            raise TypeError("job_store must be a ForgeJobStore.")
        if not callable(executor) or not callable(vault):
            raise TypeError("executor and vault must be callable.")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise TypeError("lease_seconds must be an integer.")
        if lease_seconds < 10:
            raise ValueError("lease_seconds must be at least 10.")

        self._store = job_store
        self._executor = executor
        self._vault = vault
        self._worker_id = worker_id or f"forge-worker-{uuid.uuid4().hex[:16]}"
        self._lease_seconds = lease_seconds

    def _execute_with_heartbeat(
        self,
        spec: ForgeTaskSpec,
        context: ForgeExecutionContext,
    ) -> ForgeExecutionResult:
        """Keep the lease alive for the full duration of executor work."""
        stop = threading.Event()
        interval = max(1.0, self._lease_seconds / 3.0)

        def renew_until_stopped() -> None:
            while not stop.wait(interval):
                try:
                    context.heartbeat()
                except Exception:
                    # The context records lease loss. The main worker checks
                    # it after execution and will not write using a stale lease.
                    stop.set()
                    return

        heartbeat_thread = threading.Thread(
            target=renew_until_stopped,
            name=f"forge-heartbeat-{self._worker_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = self._executor(spec, context)
        finally:
            stop.set()
            heartbeat_thread.join(timeout=max(2.0, interval + 1.0))

        if heartbeat_thread.is_alive():
            raise ForgeLeaseLost(
                "Forge heartbeat did not stop cleanly after execution."
            )
        context.check_lease()
        return result

    def run_once(self) -> ForgeJobRecord | None:
        """Recover one expired lease, then claim and process one queued job."""
        now = datetime.now(timezone.utc)
        self._store.recover_expired_lease(now)

        record = self._store.claim_next_queued(
            at=now,
            worker_id=self._worker_id,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        if record is None:
            return None

        context = ForgeExecutionContext(
            self._store, record, self._lease_seconds
        )

        try:
            spec = self._store.get_task_spec(
                record.job.business_id,
                record.job.project_id,
                record.job.job_id,
            )
            if spec is None:
                raise RuntimeError("Queued Forge job has no immutable task spec.")

            context.check_cancellation()
            context.report_progress(1, "preparing")

            result = self._execute_with_heartbeat(spec, context)
            if not isinstance(result, ForgeExecutionResult):
                raise TypeError(
                    "Forge executor must return ForgeExecutionResult."
                )

            context.check_cancellation()
            context.report_progress(95, "vaulting_candidate")

            artifact_reference = self._vault(spec, result)
            if (
                not isinstance(artifact_reference, str)
                or not artifact_reference.strip()
            ):
                raise RuntimeError(
                    "Vault did not return a valid artifact reference."
                )

            context.check_cancellation()
            context.save_checkpoint(
                {"artifact_reference": artifact_reference.strip()}
            )

            now = datetime.now(timezone.utc)
            completed = context.job.transition(
                ForgeJobStatus.COMPLETED_VAULTED, now
            )
            return self._store.update(
                replace(context._record, job=completed)
            )

        except ForgeLeaseLost:
            return self._store.get(
                record.job.business_id,
                record.job.project_id,
                record.job.job_id,
            )
        except ForgeCancellationRequested:
            try:
                return context.persist_cancellation()
            except Exception:
                # A stale worker must not overwrite the current lease owner.
                return self._store.get(
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                )

        except Exception as exc:
            if context.lease_lost:
                return self._store.get(
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                )
            try:
                now = datetime.now(timezone.utc)
                failed = context.job.transition(
                    ForgeJobStatus.FAILED,
                    now,
                    error_code="EXECUTION_FAILED",
                    error_message=str(exc)[:ForgeJob.MAX_TEXT_LENGTH],
                )
                return self._store.update(
                    replace(context._record, job=failed)
                )
            except Exception:
                # Lease fencing prevents an expired worker from overwriting
                # progress made by a replacement worker.
                return self._store.get(
                    record.job.business_id,
                    record.job.project_id,
                    record.job.job_id,
                )
