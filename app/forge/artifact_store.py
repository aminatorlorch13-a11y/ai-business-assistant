from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.persistence.database import SQLiteDatabase
from app.persistence.serialization import (
    datetime_from_storage,
    datetime_to_storage,
)


_MEDIA_TYPE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/"
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$"
)


class ArtifactIntegrityError(RuntimeError):
    """Raised when stored artifact bytes or metadata fail verification."""


@dataclass(frozen=True)
class ForgeArtifact:
    artifact_id: str
    business_id: str
    project_id: str
    sha256: str
    size_bytes: int
    media_type: str
    created_at: datetime

    @property
    def artifact_ref(self) -> str:
        return f"forge-artifact://{self.artifact_id}"


class ForgeArtifactStore:
    """Tenant-scoped metadata with immutable, content-addressed file storage."""

    DEFAULT_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
    MAX_IDENTIFIER_LENGTH = 128

    def __init__(
        self,
        database: SQLiteDatabase,
        storage_root: str | Path,
        *,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        if not isinstance(database, SQLiteDatabase):
            raise TypeError("database must be a SQLiteDatabase.")

        if not isinstance(storage_root, (str, Path)):
            raise TypeError("storage_root must be a string or Path.")

        if isinstance(max_artifact_bytes, bool) or not isinstance(
            max_artifact_bytes, int
        ):
            raise TypeError("max_artifact_bytes must be an integer.")

        if not 1 <= max_artifact_bytes <= 100 * 1024 * 1024:
            raise ValueError("max_artifact_bytes must be between 1 byte and 100 MiB.")

        if not str(storage_root).strip():
            raise ValueError("storage_root must be non-empty.")

        root = Path(storage_root).expanduser()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

        root_info = root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise ValueError("storage_root must be a real directory, not a symlink.")

        self._database = database
        self._root = root.absolute()
        self._max_artifact_bytes = max_artifact_bytes

        root_fd = self._open_root_directory()
        try:
            os.fchmod(root_fd, 0o700)
        finally:
            os.close(root_fd)

    def store(
        self,
        business_id: str,
        project_id: str,
        content: bytes,
        media_type: str,
        *,
        created_at: datetime | None = None,
    ) -> ForgeArtifact:
        self._validate_identifier("business_id", business_id)
        self._validate_identifier("project_id", project_id)

        if not isinstance(content, bytes):
            raise TypeError("content must be bytes.")

        if len(content) > self._max_artifact_bytes:
            raise ValueError("Artifact exceeds the configured size limit.")

        if not isinstance(media_type, str) or not _MEDIA_TYPE.fullmatch(media_type):
            raise ValueError("media_type must be a valid lowercase type/subtype.")

        if created_at is None:
            created_at = datetime.now(timezone.utc)

        if not isinstance(created_at, datetime):
            raise TypeError("created_at must be a datetime.")

        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware.")

        # Reject missing or archived projects before touching the filesystem.
        # Recheck inside the insert transaction to close the archive race.
        with self._database.connection() as connection:
            business = connection.execute(
                "SELECT 1 FROM businesses WHERE business_id = ?",
                (business_id,),
            ).fetchone()

            if business is None:
                raise ValueError("business_id does not reference an existing business.")

            project = connection.execute(
                """
                SELECT status
                FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()

            if project is None or project["status"] != "ACTIVE":
                raise ValueError(
                    "project_id must reference an existing active Forge project."
                )

        digest = hashlib.sha256(content).hexdigest()
        self._write_blob(digest, content)

        artifact = ForgeArtifact(
            artifact_id=uuid.uuid4().hex,
            business_id=business_id,
            project_id=project_id,
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
            created_at=created_at,
        )

        # The blob is written first. A database failure may leave an orphaned
        # blob, but cannot leave a database record pointing to a partial file.
        # Orphan reconciliation is a separate maintenance operation.
        with self._database.transaction() as connection:
            business = connection.execute(
                "SELECT 1 FROM businesses WHERE business_id = ?",
                (business_id,),
            ).fetchone()

            if business is None:
                raise ValueError("business_id does not reference an existing business.")

            project = connection.execute(
                """
                SELECT status
                FROM forge_projects
                WHERE business_id = ? AND project_id = ?
                """,
                (business_id, project_id),
            ).fetchone()

            if project is None or project["status"] != "ACTIVE":
                raise ValueError(
                    "project_id must reference an existing active Forge project."
                )

            connection.execute(
                """
                INSERT INTO forge_artifacts (
                    artifact_id,
                    business_id,
                    project_id,
                    sha256,
                    size_bytes,
                    media_type,
                    storage_key,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.business_id,
                    artifact.project_id,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.media_type,
                    artifact.sha256,
                    datetime_to_storage(artifact.created_at),
                ),
            )

        return artifact

    def get_metadata(
        self,
        artifact_id: str,
        business_id: str,
        project_id: str,
    ) -> ForgeArtifact | None:
        self._validate_identifier("artifact_id", artifact_id)
        self._validate_identifier("business_id", business_id)
        self._validate_identifier("project_id", project_id)

        with self._database.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    artifact_id,
                    business_id,
                    project_id,
                    sha256,
                    size_bytes,
                    media_type,
                    storage_key,
                    created_at
                FROM forge_artifacts
                WHERE artifact_id = ?
                  AND business_id = ?
                  AND project_id = ?
                """,
                (artifact_id, business_id, project_id),
            ).fetchone()

        if row is None:
            return None

        if row["storage_key"] != row["sha256"]:
            raise ArtifactIntegrityError("Artifact storage metadata is inconsistent.")

        if not isinstance(row["size_bytes"], int) or row["size_bytes"] < 0:
            raise ArtifactIntegrityError("Artifact size metadata is invalid.")

        try:
            created_at = datetime_from_storage(row["created_at"])
            return ForgeArtifact(
                artifact_id=row["artifact_id"],
                business_id=row["business_id"],
                project_id=row["project_id"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                media_type=row["media_type"],
                created_at=created_at,
            )
        except (TypeError, ValueError) as exc:
            raise ArtifactIntegrityError("Artifact metadata is invalid.") from exc

    def read(
        self,
        artifact_id: str,
        business_id: str,
        project_id: str,
    ) -> bytes | None:
        artifact = self.get_metadata(artifact_id, business_id, project_id)
        if artifact is None:
            return None

        content = self._read_blob(artifact.sha256)

        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != artifact.sha256:
            raise ArtifactIntegrityError("Artifact SHA-256 verification failed.")

        if len(content) != artifact.size_bytes:
            raise ArtifactIntegrityError("Artifact size verification failed.")

        return content

    def _open_root_directory(self) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(self._root, flags)
        except OSError as exc:
            raise ArtifactIntegrityError(
                "Artifact storage root cannot be opened safely."
            ) from exc

        try:
            info = os.fstat(descriptor)
            if not stat.S_ISDIR(info.st_mode):
                raise ArtifactIntegrityError(
                    "Artifact storage root is not a directory."
                )
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _open_shard(self, digest: str, *, create: bool) -> tuple[int, int]:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ArtifactIntegrityError("Artifact digest is invalid.")

        root_fd = self._open_root_directory()
        try:
            if create:
                try:
                    os.mkdir(digest[:2], mode=0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass

            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                shard_fd = os.open(digest[:2], flags, dir_fd=root_fd)
            except OSError as exc:
                raise ArtifactIntegrityError(
                    "Artifact storage shard cannot be opened safely."
                ) from exc

            try:
                if not stat.S_ISDIR(os.fstat(shard_fd).st_mode):
                    raise ArtifactIntegrityError(
                        "Artifact storage shard is not a directory."
                    )
                os.fchmod(shard_fd, 0o700)
                return root_fd, shard_fd
            except BaseException:
                os.close(shard_fd)
                raise
        except BaseException:
            os.close(root_fd)
            raise

    def _read_blob_at(self, shard_fd: int, digest: str) -> bytes:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(digest, flags, dir_fd=shard_fd)
        except FileNotFoundError as exc:
            raise ArtifactIntegrityError("Artifact file is missing.") from exc
        except OSError as exc:
            raise ArtifactIntegrityError(
                "Artifact file cannot be opened safely."
            ) from exc

        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactIntegrityError(
                    "Opened artifact is not a regular file."
                )
            if info.st_size > self._max_artifact_bytes:
                raise ArtifactIntegrityError(
                    "Stored artifact exceeds the size limit."
                )

            chunks: list[bytes] = []
            total = 0

            while True:
                remaining = self._max_artifact_bytes + 1 - total
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)

                if total > self._max_artifact_bytes:
                    raise ArtifactIntegrityError(
                        "Stored artifact exceeds the size limit."
                    )

            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _write_blob(self, digest: str, content: bytes) -> None:
        root_fd, shard_fd = self._open_shard(digest, create=True)
        lock_fd = None
        temporary_name = None

        try:
            lock_name = f".{digest}.lock"
            lock_flags = (
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            lock_fd = os.open(
                lock_name,
                lock_flags,
                0o600,
                dir_fd=shard_fd,
            )

            lock_info = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_info.st_mode):
                raise ArtifactIntegrityError(
                    "Artifact lock is not a regular file."
                )
            os.fchmod(lock_fd, 0o600)

            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            def verify_existing() -> bool:
                try:
                    info = os.stat(
                        digest,
                        dir_fd=shard_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    return False

                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise ArtifactIntegrityError(
                        "Existing artifact path is not a regular file."
                    )

                existing = self._read_blob_at(shard_fd, digest)
                if (
                    len(existing) != len(content)
                    or hashlib.sha256(existing).hexdigest() != digest
                ):
                    raise ArtifactIntegrityError(
                        "An existing content-addressed artifact is corrupted."
                    )
                return True

            if verify_existing():
                return

            temporary_name = f".tmp-{digest}-{uuid.uuid4().hex}"
            temporary_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC
            )
            descriptor = os.open(
                temporary_name,
                temporary_flags,
                0o600,
                dir_fd=shard_fd,
            )

            try:
                view = memoryview(content)
                offset = 0

                while offset < len(view):
                    written = os.write(descriptor, view[offset:])
                    if written <= 0:
                        raise OSError("Artifact write made no progress.")
                    offset += written

                os.fsync(descriptor)
            finally:
                os.close(descriptor)

            if verify_existing():
                os.unlink(temporary_name, dir_fd=shard_fd)
                temporary_name = None
                return

            os.rename(
                temporary_name,
                digest,
                src_dir_fd=shard_fd,
                dst_dir_fd=shard_fd,
            )
            temporary_name = None
            os.fsync(shard_fd)

        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=shard_fd)
                except FileNotFoundError:
                    pass

            if lock_fd is not None:
                os.close(lock_fd)

            os.close(shard_fd)
            os.close(root_fd)

    def _read_blob(self, digest: str) -> bytes:
        root_fd, shard_fd = self._open_shard(digest, create=False)
        try:
            return self._read_blob_at(shard_fd, digest)
        finally:
            os.close(shard_fd)
            os.close(root_fd)

    @classmethod
    def _validate_identifier(cls, name: str, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")

        if len(value) > cls.MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"{name} exceeds the maximum length.")
