import pytest

from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase


def schema_version(database):
    with database.connection() as connection:
        row = connection.execute(
            "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
        ).fetchone()
    return int(row["value"])


def test_fresh_database_creates_forge_artifact_table(tmp_path):
    database = SQLiteDatabase(tmp_path / "fresh.sqlite3")
    database.initialize()

    assert SCHEMA_VERSION == 17
    assert schema_version(database) == 17

    with database.connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(forge_artifacts)")
        }

    assert {
        "artifact_id",
        "business_id",
        "project_id",
        "sha256",
        "size_bytes",
        "media_type",
        "storage_key",
        "created_at",
    } <= columns

    with database.connection() as connection:
        project_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'forge_projects'"
        ).fetchone()
    assert project_table is not None


def test_v14_database_migrates_without_losing_business_data(tmp_path):
    database = SQLiteDatabase(tmp_path / "upgrade.sqlite3")
    database.initialize()

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("existing-business", "Existing", "Owner", "Assistant", "male"),
        )
        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '14'
            WHERE key = 'schema_version'
            """
        )
        connection.execute("DROP TABLE forge_artifacts")

    assert schema_version(database) == 14

    database.initialize()

    assert schema_version(database) == 17

    with database.connection() as connection:
        business = connection.execute(
            "SELECT name FROM businesses WHERE business_id = ?",
            ("existing-business",),
        ).fetchone()
        artifact_table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'forge_artifacts'
            """
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

    database = SQLiteDatabase(tmp_path / "v15-upgrade.sqlite3")
    database.initialize()

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
            """
            INSERT INTO forge_projects (
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("protected-business", "project-1", "Project", "", "ACTIVE",
             "2026-11-03T00:00:00+00:00",
             "2026-11-03T00:00:00+00:00", 0),
        )
        connection.execute(
            """
            INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "artifact-preserved",
                "protected-business",
                "project-1",
                "a" * 64,
                12,
                "text/plain",
                "a" * 64,
                "2026-11-03T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '15'
            WHERE key = 'schema_version'
            """
        )

    database.initialize()

    assert schema_version(database) == 17

    with database.connection() as connection:
        artifact = connection.execute(
            """
            SELECT business_id, sha256, size_bytes
            FROM forge_artifacts
            WHERE artifact_id = ?
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

    database = SQLiteDatabase(tmp_path / "v16-upgrade.sqlite3")
    database.initialize()

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

        connection.execute("DROP TABLE forge_artifacts")
        connection.execute("DROP TABLE forge_projects")
        connection.execute(
            """
            CREATE TABLE forge_artifacts (
                artifact_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL
                    REFERENCES businesses(business_id) ON DELETE RESTRICT,
                project_id TEXT NOT NULL,
                sha256 TEXT NOT NULL CHECK(
                    length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
                storage_key TEXT NOT NULL CHECK(length(trim(storage_key)) > 0),
                created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
                UNIQUE(business_id, project_id, artifact_id)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_forge_artifacts_project
            ON forge_artifacts(business_id, project_id, created_at)
            """
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
        connection.execute(
            "UPDATE persistence_metadata SET value = '16' WHERE key = 'schema_version'"
        )

    assert schema_version(database) == 16
    database.initialize()
    assert schema_version(database) == 17

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
