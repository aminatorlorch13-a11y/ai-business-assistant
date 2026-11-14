import pytest

from app.persistence.database import BASE_SCHEMA, MIGRATIONS, SCHEMA_VERSION, SQLiteDatabase


def schema_version(database):
    with database.connection() as connection:
        row = connection.execute(
            "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
        ).fetchone()
    return int(row["value"])


def database_at_schema_version(path, target_version):
    """Create a genuine database at the requested historical schema version."""
    if not isinstance(target_version, int) or not 1 <= target_version <= SCHEMA_VERSION:
        raise ValueError(f"Invalid target schema version: {target_version}")

    database = SQLiteDatabase(path)
    with database.connection() as connection:
        connection.executescript(BASE_SCHEMA)
        connection.execute(
            "INSERT INTO persistence_metadata(key, value) VALUES ('schema_version', '1')"
        )

        for version in range(1, target_version):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise RuntimeError(f"Missing migration {version}")

            connection.execute("BEGIN IMMEDIATE")
            try:
                migration(connection)
                connection.execute(
                    "UPDATE persistence_metadata SET value = ? WHERE key = 'schema_version'",
                    (str(version + 1),),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    return database



def test_fresh_database_creates_forge_artifact_table(tmp_path):
    database = SQLiteDatabase(tmp_path / "fresh.sqlite3")
    database.initialize()

    assert schema_version(database) == SCHEMA_VERSION

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(forge_artifacts)")
        }
        project_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forge_projects'"
        ).fetchone()

    assert {
        "artifact_id", "business_id", "project_id", "sha256",
        "size_bytes", "media_type", "storage_key", "created_at",
    } <= columns
    assert project_table is not None


def test_v14_database_migrates_without_losing_business_data(tmp_path):
    database = database_at_schema_version(tmp_path / "upgrade.sqlite3", 14)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("existing-business", "Existing", "Owner", "Assistant", "male"),
        )

    assert schema_version(database) == 14
    database.initialize()
    assert schema_version(database) == SCHEMA_VERSION

    with database.connection() as connection:
        business = connection.execute(
            "SELECT name FROM businesses WHERE business_id = ?",
            ("existing-business",),
        ).fetchone()
        artifact_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'forge_artifacts'"
        ).fetchone()

    assert business["name"] == "Existing"
    assert artifact_table is not None

def test_artifact_table_rejects_invalid_digest_and_negative_size(tmp_path):
    database = SQLiteDatabase(tmp_path / "constraints.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("b1", "Business", "Owner", "Assistant", "male"),
        )
        connection.execute(
            """
            INSERT INTO forge_projects (
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("b1", "project-1", "Project", "", "ACTIVE",
             "2026-11-03T00:00:00+00:00",
             "2026-11-03T00:00:00+00:00", 0),
        )

        base = (
            "artifact-1", "b1", "project-1", "x" * 64,
            10, "text/plain", "x" * 64, "2026-11-03T00:00:00+00:00",
        )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                base,
            )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "artifact-2", "b1", "project-1", "a" * 64,
                    -1, "text/plain", "a" * 64,
                    "2026-11-03T00:00:00+00:00",
                ),
            )




def test_v15_artifacts_restrict_business_deletion(tmp_path):
    import sqlite3

    database = database_at_schema_version(tmp_path / "v15-upgrade.sqlite3", 15)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("protected-business", "Protected", "Owner", "Assistant", "male"),
        )
        connection.execute(
            "INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "artifact-preserved", "protected-business", "project-1",
                "a" * 64, 12, "text/plain", "a" * 64,
                "2026-11-03T00:00:00+00:00",
            ),
        )

    database.initialize()
    assert schema_version(database) == SCHEMA_VERSION

    with database.connection() as connection:
        artifact = connection.execute(
            """
            SELECT business_id, sha256, size_bytes
            FROM forge_artifacts WHERE artifact_id = ?
            """,
            ("artifact-preserved",),
        ).fetchone()

    assert artifact["business_id"] == "protected-business"
    assert artifact["sha256"] == "a" * 64
    assert artifact["size_bytes"] == 12

    with database.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM businesses WHERE business_id = ?",
                ("protected-business",),
            )


def test_v16_migration_backfills_tenant_scoped_projects_and_preserves_artifacts(tmp_path):
    import sqlite3

    database = database_at_schema_version(tmp_path / "v16-upgrade.sqlite3", 16)

    with database.transaction() as connection:
        for business_id in ("tenant-a", "tenant-b"):
            connection.execute(
                """
                INSERT INTO businesses(
                    business_id, name, owner_name, assistant_name, assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, business_id, "Owner", "Assistant", "male"),
            )

        old_artifacts = (
            ("a-1", "tenant-a", "shared", "1" * 64, 10, "text/plain", "1" * 64, "2026-11-01T08:00:00+00:00"),
            ("a-2", "tenant-a", "shared", "2" * 64, 20, "text/plain", "2" * 64, "2026-11-03T08:00:00+00:00"),
            ("b-1", "tenant-b", "shared", "3" * 64, 30, "text/plain", "3" * 64, "2026-11-02T08:00:00+00:00"),
            ("b-2", "tenant-b", "tenant-b-only", "4" * 64, 40, "text/plain", "4" * 64, "2026-11-04T08:00:00+00:00"),
        )
        connection.executemany(
            "INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            old_artifacts,
        )

    assert schema_version(database) == 16
    database.initialize()
    assert schema_version(database) == SCHEMA_VERSION

    with database.connection() as connection:
        projects = connection.execute(
            """
            SELECT business_id, project_id, created_at, updated_at, legacy_imported
            FROM forge_projects ORDER BY business_id, project_id
            """
        ).fetchall()
        artifacts = connection.execute(
            "SELECT artifact_id FROM forge_artifacts"
        ).fetchall()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert len(projects) == 3
    by_key = {(r["business_id"], r["project_id"]): r for r in projects}
    assert ("tenant-a", "shared") in by_key
    assert ("tenant-b", "shared") in by_key
    assert ("tenant-b", "tenant-b-only") in by_key
    assert by_key[("tenant-a", "shared")]["legacy_imported"] == 1
    assert by_key[("tenant-a", "shared")]["created_at"] == "2026-11-01T08:00:00+00:00"
    assert by_key[("tenant-a", "shared")]["updated_at"] == "2026-11-03T08:00:00+00:00"
    assert len(artifacts) == 4
    assert not violations

    with database.transaction() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("cross-tenant", "tenant-a", "tenant-b-only", "5" * 64,
                 5, "text/plain", "5" * 64, "2026-11-05T08:00:00+00:00"),
            )


def test_v17_database_migrates_to_v18_with_tenant_scoped_forge_jobs(tmp_path):
    database = database_at_schema_version(tmp_path / "v17-upgrade.sqlite3", 17)

    database.initialize()
    assert schema_version(database) == SCHEMA_VERSION

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(forge_jobs)")
        }
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(forge_jobs)"
        ).fetchall()
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(forge_jobs)")
        }

    assert {
        "business_id", "project_id", "job_id", "job_type",
        "status", "phase", "progress", "created_at", "updated_at",
        "heartbeat_at", "started_at", "completed_at",
        "cancellation_requested", "checkpoint_json",
        "error_code", "error_message", "revision",
    } <= columns
    assert any(row["table"] == "businesses" for row in foreign_keys)
    assert any(row["table"] == "forge_projects" for row in foreign_keys)
    assert "idx_forge_jobs_project_created" in indexes
    assert "idx_forge_jobs_queue" in indexes
