from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping



class ForgeJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED_VAULTED = "completed_vaulted"
    COMPLETED_VAULTED_LOCKED = "completed_vaulted_locked"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS = {
    ForgeJobStatus.QUEUED: {
        ForgeJobStatus.RUNNING,
        ForgeJobStatus.CANCELLED,
    },
    ForgeJobStatus.RUNNING: {
        ForgeJobStatus.COMPLETED_VAULTED,
        ForgeJobStatus.FAILED,
        ForgeJobStatus.CANCELLED,
    },
    ForgeJobStatus.COMPLETED_VAULTED: {
        ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
    },
    ForgeJobStatus.COMPLETED_VAULTED_LOCKED: set(),
    ForgeJobStatus.FAILED: set(),
    ForgeJobStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class ForgeJob:
    """Validated, immutable description of one Forge background job."""

    job_id: str
    business_id: str
    project_id: str
    job_type: str
    created_at: datetime
    updated_at: datetime
    status: ForgeJobStatus = ForgeJobStatus.QUEUED
    phase: str = "queued"
    progress: int = 0
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_requested: bool = False
    checkpoint: Mapping[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    MAX_ID_LENGTH = 128
    MAX_TEXT_LENGTH = 256
    MAX_CHECKPOINT_BYTES = 16_384
    FORBIDDEN_CHECKPOINT_TERMS = frozenset({
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "credential",
        "private_key",
    })

    def __post_init__(self) -> None:
        for name in ("job_id", "business_id", "project_id"):
            self._validate_text(name, getattr(self, name), self.MAX_ID_LENGTH)

        self._validate_text("job_type", self.job_type, self.MAX_TEXT_LENGTH)
        self._validate_text("phase", self.phase, self.MAX_TEXT_LENGTH)

        if not isinstance(self.status, ForgeJobStatus):
            raise TypeError("status must be a ForgeJobStatus.")

        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime):
                raise TypeError(f"{name} must be a datetime.")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware.")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at.")

        for name in ("heartbeat_at", "started_at", "completed_at"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, datetime):
                    raise TypeError(f"{name} must be a datetime or None.")
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError(f"{name} must be timezone-aware.")
                if value < self.created_at:
                    raise ValueError(f"{name} cannot precede created_at.")
                if value > self.updated_at:
                    raise ValueError(f"{name} cannot be later than updated_at.")

        if self.heartbeat_at is not None and self.started_at is None:
            raise ValueError("A heartbeat requires a started job.")
        if (
            self.started_at is not None
            and self.heartbeat_at is not None
            and self.heartbeat_at < self.started_at
        ):
            raise ValueError("heartbeat_at cannot precede started_at.")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at cannot precede started_at.")
        if (
            self.heartbeat_at is not None
            and self.completed_at is not None
            and self.completed_at < self.heartbeat_at
        ):
            raise ValueError("completed_at cannot precede heartbeat_at.")
        if self.status == ForgeJobStatus.QUEUED and self.started_at is not None:
            raise ValueError("Queued jobs cannot have started_at.")
        if self.status == ForgeJobStatus.RUNNING and self.completed_at is not None:
            raise ValueError("Running jobs cannot have completed_at.")

        if isinstance(self.progress, bool) or not isinstance(self.progress, int):
            raise TypeError("progress must be an integer.")
        if not 0 <= self.progress <= 100:
            raise ValueError("progress must be between 0 and 100.")

        if not isinstance(self.cancellation_requested, bool):
            raise TypeError("cancellation_requested must be a bool.")

        if self.status in {
            ForgeJobStatus.COMPLETED_VAULTED,
            ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
        } and self.progress != 100:
            raise ValueError("Completed jobs must have 100 percent progress.")

        if self.status == ForgeJobStatus.RUNNING and self.started_at is None:
            raise ValueError("Running jobs must have started_at.")
        if self.status in {
            ForgeJobStatus.COMPLETED_VAULTED,
            ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
        } and self.started_at is None:
            raise ValueError("Completed jobs must have started_at.")

        if self.status in {
            ForgeJobStatus.COMPLETED_VAULTED,
            ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
            ForgeJobStatus.FAILED,
            ForgeJobStatus.CANCELLED,
        } and self.completed_at is None:
            raise ValueError("Terminal jobs must have completed_at.")

        if self.error_code is not None:
            self._validate_text("error_code", self.error_code, self.MAX_TEXT_LENGTH)

        if self.error_message is not None:
            self._validate_text(
                "error_message", self.error_message, self.MAX_TEXT_LENGTH
            )

        if self.status == ForgeJobStatus.FAILED and not self.error_code:
            raise ValueError("Failed jobs must have an error_code.")

        if self.status != ForgeJobStatus.FAILED and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("Only failed jobs may contain error details.")

        if self.checkpoint is not None:
            object.__setattr__(
                self, "checkpoint", self._validate_checkpoint(self.checkpoint)
            )

    @classmethod
    def _validate_text(cls, name: str, value: object, maximum: int) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        if len(value) > maximum:
            raise ValueError(f"{name} exceeds the maximum length.")

    @classmethod
    def _validate_checkpoint(
        cls, value: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("checkpoint must be a mapping.")

        def validate(item: Any, depth: int = 0) -> Any:
            if depth > 5:
                raise ValueError("checkpoint nesting is too deep.")

            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Checkpoint numbers must be finite.")
            if item is None or isinstance(item, (bool, int, float)):
                return item

            if isinstance(item, str):
                if len(item) > 2048:
                    raise ValueError("checkpoint string is too long.")
                return item

            if isinstance(item, Mapping):
                if len(item) > 64:
                    raise ValueError("checkpoint contains too many keys.")
                result = {}
                for key, nested in item.items():
                    if not isinstance(key, str) or not key.strip():
                        raise ValueError("checkpoint keys must be non-empty strings.")
                    normalized = key.strip().lower()
                    if any(
                        term == normalized or term in normalized
                        for term in cls.FORBIDDEN_CHECKPOINT_TERMS
                    ):
                        raise ValueError("Checkpoint contains a forbidden key.")
                    result[key] = validate(nested, depth + 1)
                return result

            if isinstance(item, (list, tuple)):
                if len(item) > 64:
                    raise ValueError("checkpoint list is too large.")
                return [validate(nested, depth + 1) for nested in item]

            raise TypeError("Checkpoint values must be JSON-compatible.")

        cleaned = validate(value)
        encoded = json.dumps(
            cleaned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) > cls.MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint exceeds the maximum serialized size.")

        decoded = json.loads(encoded)

        def freeze(item: Any) -> Any:
            if isinstance(item, dict):
                return MappingProxyType({
                    key: freeze(value) for key, value in item.items()
                })
            if isinstance(item, list):
                return tuple(freeze(value) for value in item)
            return item

        return freeze(decoded)

    def transition(
        self, new_status: ForgeJobStatus, at: datetime, *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ForgeJob:
        if not isinstance(new_status, ForgeJobStatus):
            raise TypeError("new_status must be a ForgeJobStatus.")
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be a timezone-aware datetime.")
        if at < self.updated_at:
            raise ValueError("Transition time cannot move backwards.")
        if new_status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"Transition not allowed: {self.status.value} -> {new_status.value}."
            )

        if new_status == ForgeJobStatus.FAILED:
            self._validate_text("error_code", error_code, self.MAX_TEXT_LENGTH)
            if error_message is not None:
                self._validate_text(
                    "error_message", error_message, self.MAX_TEXT_LENGTH
                )
        elif error_code is not None or error_message is not None:
            raise ValueError("Error details are only valid for failed jobs.")

        changes: dict[str, Any] = {
            "status": new_status,
            "updated_at": at,
        }

        if new_status == ForgeJobStatus.RUNNING:
            changes.update(started_at=at, phase="running")

        if new_status in {
            ForgeJobStatus.COMPLETED_VAULTED,
            ForgeJobStatus.COMPLETED_VAULTED_LOCKED,
        }:
            changes.update(
                progress=100,
                completed_at=at,
                phase=new_status.value,
            )

        if new_status in {ForgeJobStatus.FAILED, ForgeJobStatus.CANCELLED}:
            changes.update(completed_at=at, phase=new_status.value)

        if new_status == ForgeJobStatus.FAILED:
            changes.update(
                error_code=error_code,
                error_message=error_message,
            )

        return replace(self, **changes)

    def update_progress(
        self, progress: int, phase: str, at: datetime
    ) -> ForgeJob:
        if self.status != ForgeJobStatus.RUNNING:
            raise ValueError("Progress can only change while a job is running.")
        if isinstance(progress, bool) or not isinstance(progress, int):
            raise TypeError("progress must be an integer.")
        if not 0 <= progress <= 99:
            raise ValueError("Running-job progress must be between 0 and 99.")
        if progress < self.progress:
            raise ValueError("Progress cannot move backwards.")
        self._validate_text("phase", phase, self.MAX_TEXT_LENGTH)
        self._validate_timestamp(at)

        return replace(
            self,
            progress=progress,
            phase=phase,
            updated_at=at,
        )

    def heartbeat(self, at: datetime) -> ForgeJob:
        if self.status != ForgeJobStatus.RUNNING:
            raise ValueError("Only running jobs can receive heartbeats.")
        self._validate_timestamp(at)
        if self.heartbeat_at is not None and at < self.heartbeat_at:
            raise ValueError("Heartbeat time cannot move backwards.")

        return replace(self, heartbeat_at=at, updated_at=at)

    def save_checkpoint(
        self, checkpoint: Mapping[str, Any], at: datetime
    ) -> ForgeJob:
        if self.status != ForgeJobStatus.RUNNING:
            raise ValueError("Checkpoints can only be saved while running.")
        self._validate_timestamp(at)
        return replace(
            self,
            checkpoint=self._validate_checkpoint(checkpoint),
            updated_at=at,
        )

    def request_cancellation(self, at: datetime) -> ForgeJob:
        self._validate_timestamp(at)

        if self.status == ForgeJobStatus.QUEUED:
            return self.transition(ForgeJobStatus.CANCELLED, at)

        if self.status == ForgeJobStatus.RUNNING:
            return replace(
                self,
                cancellation_requested=True,
                updated_at=at,
            )

        raise ValueError("Cancellation cannot be requested for a finished job.")

    def _validate_timestamp(self, at: datetime) -> None:
        if not isinstance(at, datetime):
            raise TypeError("at must be a datetime.")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware.")
        if at < self.updated_at:
            raise ValueError("Operation time cannot move backwards.")
