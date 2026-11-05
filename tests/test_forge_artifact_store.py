import hashlib
import os
import sqlite3

import pytest

from app.forge.artifact_store import (
    ArtifactIntegrityError,
    ForgeArtifactStore,
)
from app.persistence.database import SQLiteDatabase


def make_store(tmp_path, *, max_bytes=1024):
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("business-1", "Business", "Owner", "Assistant", "male"),
        )
        connection.execute(
            """
            INSERT INTO forge_projects (
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("business-1", "project-1", "Test Project", "", "ACTIVE",
             "2026-11-03T00:00:00+00:00",
             "2026-11-03T00:00:00+00:00", 0),
        )

    store = ForgeArtifactStore(
        database,
        tmp_path / "private-artifacts",
        max_artifact_bytes=max_bytes,
    )
    return database, store


def test_store_and_read_verifies_content(tmp_path):
    _, store = make_store(tmp_path)
    content = b"real artifact bytes"

    artifact = store.store(
        "business-1",
        "project-1",
        content,
        "text/plain",
    )

    assert artifact.sha256 == hashlib.sha256(content).hexdigest()
    assert artifact.size_bytes == len(content)
    assert artifact.artifact_ref == f"forge-artifact://{artifact.artifact_id}"
    assert store.read(
        artifact.artifact_id,
        "business-1",
        "project-1",
    ) == content


def test_metadata_is_scoped_to_business_and_project(tmp_path):
    _, store = make_store(tmp_path)
    artifact = store.store(
        "business-1",
        "project-1",
        b"private",
        "text/plain",
    )

    assert store.get_metadata(
        artifact.artifact_id,
        "business-2",
        "project-1",
    ) is None

    assert store.get_metadata(
        artifact.artifact_id,
        "business-1",
        "project-2",
    ) is None

    assert store.read(
        artifact.artifact_id,
        "business-2",
        "project-1",
    ) is None


def test_identical_content_uses_same_blob_but_distinct_records(tmp_path):
    _, store = make_store(tmp_path)
    content = b"same content"

    first = store.store("business-1", "project-1", content, "text/plain")
    second = store.store("business-1", "project-1", content, "text/plain")

    assert first.artifact_id != second.artifact_id
    assert first.sha256 == second.sha256
    assert store.read(first.artifact_id, "business-1", "project-1") == content
    assert store.read(second.artifact_id, "business-1", "project-1") == content

    blob = tmp_path / "private-artifacts" / first.sha256[:2] / first.sha256
    assert blob.is_file()


def test_corrupted_blob_is_rejected_on_read(tmp_path):
    _, store = make_store(tmp_path)
    artifact = store.store(
        "business-1",
        "project-1",
        b"original",
        "text/plain",
    )

    blob = tmp_path / "private-artifacts" / artifact.sha256[:2] / artifact.sha256
    blob.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.read(artifact.artifact_id, "business-1", "project-1")


def test_missing_blob_is_rejected_on_read(tmp_path):
    _, store = make_store(tmp_path)
    artifact = store.store(
        "business-1",
        "project-1",
        b"original",
        "text/plain",
    )

    blob = tmp_path / "private-artifacts" / artifact.sha256[:2] / artifact.sha256
    blob.unlink()

    with pytest.raises(ArtifactIntegrityError):
        store.read(artifact.artifact_id, "business-1", "project-1")


def test_missing_business_is_rejected(tmp_path):
    _, store = make_store(tmp_path)

    with pytest.raises(ValueError, match="existing business"):
        store.store(
            "missing-business",
            "project-1",
            b"content",
            "text/plain",
        )


def test_string_content_is_rejected(tmp_path):
    _, store = make_store(tmp_path)

    with pytest.raises(TypeError):
        store.store("business-1", "project-1", "not bytes", "text/plain")


def test_oversized_content_is_rejected(tmp_path):
    _, store = make_store(tmp_path, max_bytes=4)

    with pytest.raises(ValueError, match="size limit"):
        store.store("business-1", "project-1", b"12345", "text/plain")


def test_invalid_media_type_is_rejected(tmp_path):
    _, store = make_store(tmp_path)

    for media_type in ("TEXT/PLAIN", "text", "../text/plain", "text/plain\n"):
        with pytest.raises(ValueError):
            store.store("business-1", "project-1", b"x", media_type)


def test_naive_timestamp_is_rejected(tmp_path):
    from datetime import datetime

    _, store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.store(
            "business-1",
            "project-1",
            b"x",
            "text/plain",
            created_at=datetime(2026, 11, 3),
        )


def test_existing_corrupt_digest_path_is_not_overwritten(tmp_path):
    _, store = make_store(tmp_path)
    content = b"expected"
    digest = hashlib.sha256(content).hexdigest()

    shard = tmp_path / "private-artifacts" / digest[:2]
    shard.mkdir(parents=True)
    (shard / digest).write_bytes(b"corrupt")

    with pytest.raises(ArtifactIntegrityError):
        store.store("business-1", "project-1", content, "text/plain")

    assert (shard / digest).read_bytes() == b"corrupt"


def test_symlink_blob_is_rejected(tmp_path):
    _, store = make_store(tmp_path)
    content = b"expected"
    digest = hashlib.sha256(content).hexdigest()

    shard = tmp_path / "private-artifacts" / digest[:2]
    shard.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(content)
    (shard / digest).symlink_to(outside)

    with pytest.raises(ArtifactIntegrityError):
        store.store("business-1", "project-1", content, "text/plain")


def test_symlink_storage_root_is_rejected(tmp_path):
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()

    real_root = tmp_path / "real-root"
    real_root.mkdir()
    link_root = tmp_path / "linked-root"
    link_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        ForgeArtifactStore(database, link_root)


def test_artifact_metadata_survives_database_restart(tmp_path):
    database, store = make_store(tmp_path)
    artifact = store.store(
        "business-1",
        "project-1",
        b"persistent",
        "text/plain",
    )

    reopened = SQLiteDatabase(database.path)
    reopened.initialize()
    reopened_store = ForgeArtifactStore(
        reopened,
        tmp_path / "private-artifacts",
        max_artifact_bytes=1024,
    )

    assert reopened_store.read(
        artifact.artifact_id,
        "business-1",
        "project-1",
    ) == b"persistent"


def test_repository_does_not_expose_artifact_deletion(tmp_path):
    _, store = make_store(tmp_path)

    assert not hasattr(store, "delete")
    assert not hasattr(store, "remove")


def test_concurrent_identical_writes_publish_one_valid_blob(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    database, store = make_store(tmp_path)
    content = b"concurrent artifact publication" * 10

    def save(_):
        return store.store(
            "business-1", "project-1", content, "application/octet-stream"
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        artifacts = list(executor.map(save, range(16)))

    assert len({item.artifact_id for item in artifacts}) == 16
    assert len({item.sha256 for item in artifacts}) == 1

    for artifact in artifacts:
        assert store.read(
            artifact.artifact_id, "business-1", "project-1"
        ) == content

    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM forge_artifacts"
        ).fetchone()[0]
    assert count == 16


def test_storage_root_and_shard_have_private_permissions(tmp_path):
    import stat

    _, store = make_store(tmp_path)
    artifact = store.store(
        "business-1", "project-1", b"private", "text/plain"
    )

    root = tmp_path / "private-artifacts"
    shard = root / artifact.sha256[:2]

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(shard.stat().st_mode) == 0o700


def test_symlink_shard_is_rejected(tmp_path):
    _, store = make_store(tmp_path)
    content = b"shard symlink test"
    digest = hashlib.sha256(content).hexdigest()

    root = tmp_path / "private-artifacts"
    outside = tmp_path / "outside-shard"
    outside.mkdir()
    (outside / digest).write_bytes(content)

    (root / digest[:2]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactIntegrityError):
        store.store("business-1", "project-1", content, "text/plain")



def test_missing_project_is_rejected_before_blob_publication(tmp_path):
    _, store = make_store(tmp_path)
    root = tmp_path / "private-artifacts"

    with pytest.raises(ValueError, match="existing active Forge project"):
        store.store(
            "business-1",
            "missing-project",
            b"must not be published",
            "text/plain",
        )

    assert list(root.iterdir()) == []


def test_archived_project_cannot_receive_new_artifacts(tmp_path):
    database, store = make_store(tmp_path)
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE forge_projects
            SET status = 'ARCHIVED'
            WHERE business_id = ? AND project_id = ?
            """,
            ("business-1", "project-1"),
        )

    root = tmp_path / "private-artifacts"
    with pytest.raises(ValueError, match="existing active Forge project"):
        store.store(
            "business-1",
            "project-1",
            b"archived project content",
            "text/plain",
        )

    assert list(root.iterdir()) == []
