import pytest

from app.forge.project_repository_store import (
    ForgeProjectRepositoryStore,
    RepositoryAlreadyBoundError,
)
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase
from app.forge.project_store import ForgeProjectStore


@pytest.fixture
def repository_store(tmp_path):
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        for business_id in ("business-1", "business-2"):
            connection.execute(
                """
                INSERT INTO businesses (
                    business_id, name, owner_name, assistant_name, assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, "Business", "Owner", "Assistant", "male"),
            )
    projects = ForgeProjectStore(database)
    projects.create("business-1", "project-1", "Website")
    projects.create("business-2", "project-1", "Other tenant")
    return database, ForgeProjectRepositoryStore(database)


def test_schema_migrates_to_repository_binding_version(repository_store):
    database, _ = repository_store
    assert SCHEMA_VERSION >= 21
    with database.connection() as connection:
        version = connection.execute(
            "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
        ).fetchone()["value"]
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(forge_project_repositories)"
            ).fetchall()
        }
    assert version == str(SCHEMA_VERSION)
    assert {
        "business_id", "project_id", "provider", "repository_owner",
        "repository_name", "default_branch", "created_at", "updated_at",
    } <= columns


def test_register_and_get_repository(repository_store):
    _, store = repository_store
    created = store.register(
        "business-1", "project-1", "amination", "ai-business-assistant"
    )
    assert store.get("business-1", "project-1") == created
    assert created.provider == "github"
    assert created.clone_url == (
        "https://github.com/amination/ai-business-assistant.git"
    )


def test_repository_identity_is_tenant_scoped(repository_store):
    _, store = repository_store
    store.register("business-1", "project-1", "owner-one", "repo-one")
    assert store.get("business-2", "project-1") is None


def test_second_repository_binding_is_rejected(repository_store):
    _, store = repository_store
    store.register("business-1", "project-1", "owner", "first")
    with pytest.raises(RepositoryAlreadyBoundError):
        store.register("business-1", "project-1", "owner", "second")


def test_missing_project_cannot_be_bound(repository_store):
    _, store = repository_store
    with pytest.raises(ValueError, match="active Forge project"):
        store.register("business-1", "missing", "owner", "repo")


def test_archived_project_cannot_be_bound(repository_store):
    database, store = repository_store
    ForgeProjectStore(database).archive("business-1", "project-1")
    with pytest.raises(ValueError, match="active Forge project"):
        store.register("business-1", "project-1", "owner", "repo")


@pytest.mark.parametrize(
    "owner",
    ["", "-owner", "owner-", "two words", "owner/name", "x" * 40],
)
def test_invalid_github_owner_is_rejected(repository_store, owner):
    _, store = repository_store
    with pytest.raises(ValueError, match="GitHub owner"):
        store.register("business-1", "project-1", owner, "repo")


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "two words", "repo/name", "x" * 101],
)
def test_invalid_repository_name_is_rejected(repository_store, name):
    _, store = repository_store
    with pytest.raises(ValueError, match="repository_name"):
        store.register("business-1", "project-1", "owner", name)


@pytest.mark.parametrize(
    "branch",
    [
        "", "../main", "main..evil", "main branch", "-option",
        "feature//bad", "feature/.hidden", "feature/name.lock",
        "feature\\name", "HEAD",
    ],
)
def test_unsafe_git_branch_is_rejected(repository_store, branch):
    _, store = repository_store
    with pytest.raises(ValueError, match="branch"):
        store.register(
            "business-1", "project-1", "owner", "repo",
            default_branch=branch,
        )


def test_valid_nested_branch_is_accepted(repository_store):
    _, store = repository_store
    result = store.register(
        "business-1", "project-1", "owner", "repo",
        default_branch="release/2026/stable",
    )
    assert result.default_branch == "release/2026/stable"


def test_wrong_database_type_is_rejected():
    with pytest.raises(TypeError, match="SQLiteDatabase"):
        ForgeProjectRepositoryStore("database.sqlite3")
