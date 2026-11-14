from pathlib import Path

p = Path("tests/test_forge_artifact_migration.py")
s = p.read_text()

assert "assert SCHEMA_VERSION == 16" in s
assert "assert schema_version(database) == 16" in s
s = s.replace("assert SCHEMA_VERSION == 16", "assert SCHEMA_VERSION == 17")
s = s.replace("assert schema_version(database) == 16", "assert schema_version(database) == 17")

# Give direct constraint tests a valid parent project.
needle = '''            ("b1", "Business", "Owner", "Assistant", "male"),
        )

        base = (
'''
assert needle in s
s = s.replace(needle, '''            ("b1", "Business", "Owner", "Assistant", "male"),
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
''', 1)

# Give the v15 upgrade fixture a valid project parent.
needle = '''            ("protected-business", "Protected", "Owner", "Assistant", "male"),
        )
        connection.execute(
            """
            INSERT INTO forge_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
'''
assert needle in s
s = s.replace(needle, '''            ("protected-business", "Protected", "Owner", "Assistant", "male"),
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
''', 1)

# Assert the new project table exists on a fresh database.
needle = '''    } <= columns
'''
assert needle in s
s = s.replace(needle, needle + '''
    with database.connection() as connection:
        project_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'forge_projects'"
        ).fetchone()
    assert project_table is not None
''', 1)

# Test a real v16 -> v17 upgrade with legacy artifact backfill.
s += '''


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
'''

p.write_text(s)

p = Path("tests/test_forge_artifact_store.py")
s = p.read_text()
needle = '''            ("business-1", "Business", "Owner", "Assistant", "male"),
        )

    store = ForgeArtifactStore(
'''
assert needle in s
s = s.replace(needle, '''            ("business-1", "Business", "Owner", "Assistant", "male"),
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
''', 1)
p.write_text(s)

print("Forge v17 migration tests and artifact-store fixture updated.")
