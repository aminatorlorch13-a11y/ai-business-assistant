from pathlib import Path

path = Path("app/persistence/database.py")
source = path.read_text()

required = [
    "SCHEMA_VERSION = 16",
    "def _migrate_v15_to_v16",
    "15: _migrate_v15_to_v16,",
    "MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {",
]
for item in required:
    if item not in source:
        raise SystemExit(f"STOP: expected source not found: {item}")

if "def _migrate_v16_to_v17" in source:
    raise SystemExit("STOP: v17 migration already exists.")

migration = r'''

def _migrate_v16_to_v17(connection: sqlite3.Connection) -> None:
    """Create tenant-scoped Forge projects and bind artifacts to their owner."""
    from datetime import datetime, timezone

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS forge_projects (
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL
                CHECK(length(trim(project_id)) > 0 AND length(project_id) <= 128),
            name TEXT NOT NULL
                CHECK(length(trim(name)) > 0 AND length(name) <= 160),
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK(status IN ('ACTIVE', 'ARCHIVED')),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            legacy_imported INTEGER NOT NULL DEFAULT 0
                CHECK(legacy_imported IN (0, 1)),
            PRIMARY KEY(business_id, project_id),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            CHECK(updated_at >= created_at)
        )
        """
    )

    legacy_rows = connection.execute(
        """
        SELECT business_id, project_id, created_at
        FROM forge_artifacts
        ORDER BY business_id, project_id
        """
    ).fetchall()

    project_times: dict[tuple[str, str], list[datetime]] = {}
    for row in legacy_rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Cannot migrate Forge artifact with an invalid creation timestamp."
            ) from exc

        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuntimeError(
                "Cannot migrate Forge artifact with a timezone-naive timestamp."
            )

        key = (row["business_id"], row["project_id"])
        project_times.setdefault(key, []).append(
            created_at.astimezone(timezone.utc)
        )

    for (business_id, project_id), timestamps in project_times.items():
        first_seen = min(timestamps).isoformat()
        last_seen = max(timestamps).isoformat()

        connection.execute(
            """
            INSERT OR IGNORE INTO forge_projects (
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            )
            VALUES (?, ?, ?, ?, 'ACTIVE', ?, ?, 1)
            """,
            (
                business_id,
                project_id,
                f"Imported project {project_id}",
                "Imported from existing Forge artifact records. Original project "
                "description and creation history were not available.",
                first_seen,
                last_seen,
            ),
        )

    connection.execute("DROP INDEX IF EXISTS idx_forge_artifacts_project")
    connection.execute("ALTER TABLE forge_artifacts RENAME TO forge_artifacts_v16")

    connection.execute(
        """
        CREATE TABLE forge_artifacts (
            artifact_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            sha256 TEXT NOT NULL
                CHECK(
                    length(sha256) = 64
                    AND sha256 NOT GLOB '*[^0-9a-f]*'
                ),
            size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            media_type TEXT NOT NULL CHECK(length(trim(media_type)) > 0),
            storage_key TEXT NOT NULL CHECK(length(trim(storage_key)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            FOREIGN KEY(business_id)
                REFERENCES businesses(business_id)
                ON DELETE RESTRICT,
            FOREIGN KEY(business_id, project_id)
                REFERENCES forge_projects(business_id, project_id)
                ON DELETE RESTRICT,
            UNIQUE(business_id, project_id, artifact_id)
        )
        """
    )

    connection.execute(
        """
        INSERT INTO forge_artifacts (
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        )
        SELECT
            artifact_id, business_id, project_id, sha256,
            size_bytes, media_type, storage_key, created_at
        FROM forge_artifacts_v16
        """
    )
    connection.execute("DROP TABLE forge_artifacts_v16")

    connection.execute(
        """
        CREATE INDEX idx_forge_artifacts_project
        ON forge_artifacts(business_id, project_id, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_forge_projects_business_status
        ON forge_projects(business_id, status, updated_at)
        """
    )

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "Forge project migration produced foreign-key violations."
        )
'''

source = source.replace("SCHEMA_VERSION = 16", "SCHEMA_VERSION = 17", 1)
anchor = "\nMIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {"
source = source.replace(anchor, migration + anchor, 1)
source = source.replace(
    "    15: _migrate_v15_to_v16,\n",
    "    15: _migrate_v15_to_v16,\n    16: _migrate_v16_to_v17,\n",
    1,
)

temporary = path.with_suffix(".py.forge-v17-tmp")
temporary.write_text(source)
temporary.replace(path)
print("Database source updated: Forge migration v16 -> v17.")
