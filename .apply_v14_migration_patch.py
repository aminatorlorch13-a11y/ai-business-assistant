from datetime import datetime
from pathlib import Path
import os
import shutil
import tempfile

root = Path.cwd()
database_path = root / "app/persistence/database.py"
tests_path = root / "tests/test_d5_safety_migration.py"

database = database_path.read_text()
tests = tests_path.read_text()

migration = '''
def _migrate_v13_to_v14(connection: sqlite3.Connection) -> None:
    """Add durable, membership-scoped voice conversation history."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
            FOREIGN KEY(user_id, business_id)
                REFERENCES business_memberships(user_id, business_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_conversations_owner_updated
        ON voice_conversations(user_id, business_id, updated_at)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_conversation_turns (
            conversation_id TEXT NOT NULL,
            sequence INTEGER NOT NULL CHECK(sequence > 0),
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL CHECK(length(trim(content)) > 0),
            created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
            PRIMARY KEY(conversation_id, sequence),
            FOREIGN KEY(conversation_id)
                REFERENCES voice_conversations(conversation_id)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_turns_conversation_sequence
        ON voice_conversation_turns(conversation_id, sequence)
        """
    )

'''

registry_anchor = "    12: _migrate_v12_to_v13,\n"
function_anchor = "MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {"
version_anchor = "SCHEMA_VERSION = 13"
test_anchor = "    assert SCHEMA_VERSION == 13"

checks = {
    "schema version anchor": database.count(version_anchor) == 1,
    "migration registry anchor": database.count(registry_anchor) == 1,
    "migration function anchor": database.count(function_anchor) == 1,
    "test version assertion": tests.count(test_anchor) == 1,
    "no existing v14 migration": "_migrate_v13_to_v14" not in database,
    "no existing v14 migration test": "test_v13_to_v14_creates_voice_history" not in tests,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(
        "PATCH ABORTED; no files written. Unexpected source state: "
        + ", ".join(failed)
    )

database_new = database.replace(version_anchor, "SCHEMA_VERSION = 14", 1)
database_new = database_new.replace(
    function_anchor,
    migration + function_anchor,
    1,
)
database_new = database_new.replace(
    registry_anchor,
    registry_anchor + "    13: _migrate_v13_to_v14,\n",
    1,
)

tests_new = tests.replace(test_anchor, "    assert SCHEMA_VERSION == 14", 1)

tests_new += '''

def test_v13_to_v14_creates_voice_history(tmp_path):
    db = SQLiteDatabase(tmp_path / "v13-to-v14.db")
    db.initialize()

    # Create a genuine v13-shaped state while preserving existing owner data.
    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO businesses(
                business_id, name, owner_name, assistant_name, assistant_voice
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("voice-business", "Voice Business", "Owner", "Assistant", "calm"),
        )
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            ("voice-user", "Voice User", "voice-user@example.test"),
        )
        connection.execute(
            """
            INSERT INTO business_memberships(user_id, business_id, role)
            VALUES (?, ?, ?)
            """,
            ("voice-user", "voice-business", "owner"),
        )
        connection.execute("DROP TABLE IF EXISTS voice_conversation_turns")
        connection.execute("DROP TABLE IF EXISTS voice_conversations")
        connection.execute(
            """
            UPDATE persistence_metadata
            SET value = '13'
            WHERE key = 'schema_version'
            """
        )

    assert _schema_version(db) == 13
    db.initialize()
    assert _schema_version(db) == 14

    with db.connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name IN (
                      'voice_conversations',
                      'voice_conversation_turns'
                  )
                """
            ).fetchall()
        }
        membership = connection.execute(
            """
            SELECT role FROM business_memberships
            WHERE user_id = ? AND business_id = ?
            """,
            ("voice-user", "voice-business"),
        ).fetchone()

    assert tables == {
        "voice_conversations",
        "voice_conversation_turns",
    }
    assert membership is not None
    assert membership["role"] == "owner"

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO voice_conversations(
                conversation_id, user_id, business_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "voice-conversation-1",
                "voice-user",
                "voice-business",
                "2026-10-14T10:00:00+00:00",
                "2026-10-14T10:00:00+00:00",
            ),
        )

    with db.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO voice_conversation_turns(
                    conversation_id, sequence, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "voice-conversation-1", 1, "system", "invalid role",
                    "2026-10-14T10:00:00+00:00",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO voice_conversation_turns(
                    conversation_id, sequence, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "voice-conversation-1", 1, "user", "   ",
                    "2026-10-14T10:00:00+00:00",
                ),
            )

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO voice_conversation_turns(
                conversation_id, sequence, role, content, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "voice-conversation-1", 1, "user", "Keep this history",
                "2026-10-14T10:00:00+00:00",
            ),
        )
        # Removing membership cascades through conversations to their turns.
        connection.execute(
            """
            DELETE FROM business_memberships
            WHERE user_id = ? AND business_id = ?
            """,
            ("voice-user", "voice-business"),
        )

    with db.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM voice_conversations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM voice_conversation_turns"
        ).fetchone()[0] == 0
'''

backup_dir = Path.home() / (
    "ai-business-assistant-safety-v14-"
    + datetime.now().strftime("%Y%m%d-%H%M%S")
)
backup_dir.mkdir(parents=True, exist_ok=False)
shutil.copy2(database_path, backup_dir / "database.py")
shutil.copy2(tests_path, backup_dir / "test_d5_safety_migration.py")

def atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise

atomic_write(database_path, database_new)
atomic_write(tests_path, tests_new)

print("v14 migration and tests patched.")
print(f"Backup: {backup_dir}")
print("No production database was opened or modified.")
