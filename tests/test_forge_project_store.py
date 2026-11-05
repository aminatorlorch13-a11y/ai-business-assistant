import pytest

from app.forge.project import ProjectStatus
from app.forge.project_store import (
    ForgeProjectStore,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from app.persistence.database import SQLiteDatabase


@pytest.fixture
def project_store(tmp_path):
    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        for business_id in ("business-1", "business-2"):
            connection.execute(
                """
                INSERT INTO businesses(
                    business_id, name, owner_name, assistant_name, assistant_voice
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (business_id, "Business", "Owner", "Assistant", "male"),
            )
    return ForgeProjectStore(database)


def test_create_and_get_project(project_store):
    created = project_store.create(
        "business-1", "project-1", "Website", "Company website"
    )
    found = project_store.get("business-1", "project-1")
    assert found == created
    assert found.status is ProjectStatus.ACTIVE
    assert found.legacy_imported is False


def test_same_project_id_can_belong_to_different_businesses(project_store):
    first = project_store.create("business-1", "same-id", "First")
    second = project_store.create("business-2", "same-id", "Second")
    assert first.business_id != second.business_id
    assert project_store.get("business-1", "same-id").name == "First"
    assert project_store.get("business-2", "same-id").name == "Second"


def test_duplicate_project_is_rejected(project_store):
    project_store.create("business-1", "project-1", "First")
    with pytest.raises(ProjectAlreadyExistsError):
        project_store.create("business-1", "project-1", "Duplicate")


def test_missing_business_is_rejected(project_store):
    with pytest.raises(ValueError, match="existing business"):
        project_store.create("missing", "project-1", "Project")


def test_project_lookup_is_business_scoped(project_store):
    project_store.create("business-1", "project-1", "Private")
    assert project_store.get("business-2", "project-1") is None


def test_list_is_scoped_to_business(project_store):
    project_store.create("business-1", "one", "One")
    project_store.create("business-2", "two", "Two")
    projects = project_store.list_for_business("business-1")
    assert [item.project_id for item in projects] == ["one"]


def test_update_changes_only_supplied_fields(project_store):
    original = project_store.create(
        "business-1", "project-1", "Old name", "Old description"
    )
    updated = project_store.update(
        "business-1", "project-1", name="New name"
    )
    assert updated.name == "New name"
    assert updated.description == "Old description"
    assert updated.created_at == original.created_at
    assert updated.updated_at >= original.updated_at


def test_update_rejects_empty_change(project_store):
    project_store.create("business-1", "project-1", "Project")
    with pytest.raises(ValueError, match="at least one"):
        project_store.update("business-1", "project-1")


def test_archive_and_active_filter(project_store):
    project_store.create("business-1", "project-1", "Project")
    archived = project_store.archive("business-1", "project-1")
    assert archived.status is ProjectStatus.ARCHIVED
    assert project_store.get("business-1", "project-1") is not None
    assert project_store.list_for_business(
        "business-1", active_only=True
    ) == []


def test_archive_is_idempotent(project_store):
    project_store.create("business-1", "project-1", "Project")
    first = project_store.archive("business-1", "project-1")
    second = project_store.archive("business-1", "project-1")
    assert second.status is ProjectStatus.ARCHIVED
    assert second.updated_at == first.updated_at


def test_archived_project_cannot_be_updated(project_store):
    project_store.create("business-1", "project-1", "Project")
    project_store.archive("business-1", "project-1")
    with pytest.raises(ValueError, match="Archived"):
        project_store.update("business-1", "project-1", name="Changed")


def test_missing_project_update_and_archive_fail(project_store):
    with pytest.raises(ProjectNotFoundError):
        project_store.update("business-1", "missing", name="Name")
    with pytest.raises(ProjectNotFoundError):
        project_store.archive("business-1", "missing")


def test_legacy_import_flag_is_preserved(project_store):
    with project_store._database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO forge_projects(
                business_id, project_id, name, description, status,
                created_at, updated_at, legacy_imported
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "business-1", "legacy", "Imported", "",
                "ACTIVE", "2026-11-03T00:00:00+00:00",
                "2026-11-03T00:00:00+00:00", 1,
            ),
        )
    updated = project_store.update(
        "business-1", "legacy", description="Details added"
    )
    assert updated.legacy_imported is True


def test_invalid_identifiers_and_text_are_rejected(project_store):
    with pytest.raises(ValueError):
        project_store.create(" ", "project-1", "Name")
    with pytest.raises(ValueError):
        project_store.create("business-1", "project-1", " ")
    with pytest.raises(ValueError):
        project_store.create("business-1", "project-1", " Name ")
    with pytest.raises(ValueError):
        project_store.create(
            "business-1", "project-1", "x" * 161
        )


def test_wrong_database_type_is_rejected():
    with pytest.raises(TypeError):
        ForgeProjectStore("database.sqlite3")
