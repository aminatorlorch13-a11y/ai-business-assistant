from types import SimpleNamespace

from app.identity.models import UserRole
from app.owner.models import OwnerLifestylePreferences
from app.owner.repository import SQLiteOwnerLifestyleRepository
from app.owner.service import OwnerLifestyleService
from app.persistence.business_repository import (
    Business,
    SQLiteBusinessRepository,
)
from app.persistence.database import SQLiteDatabase
from app.persistence.membership_repository import (
    BusinessMembership,
    SQLiteMembershipRepository,
)
from app.persistence.user_repository import User, SQLiteUserRepository


def make_owner_environment(tmp_path):
    db = SQLiteDatabase(str(tmp_path / "owner-lifestyle.sqlite3"))
    db.initialize()

    users = SQLiteUserRepository(db)
    businesses = SQLiteBusinessRepository(db)
    memberships = SQLiteMembershipRepository(db)
    repository = SQLiteOwnerLifestyleRepository(db)

    users.save(User("owner-1", "Test Owner", "owner@example.test"))
    businesses.save(
        Business(
            "business-1",
            "Test Business",
            "Test Owner",
            "Assistant",
            "female",
        )
    )
    memberships.save(
        BusinessMembership("owner-1", "business-1", UserRole.OWNER)
    )

    principal = SimpleNamespace(
        user_id="owner-1",
        business_id="business-1",
    )

    service = OwnerLifestyleService(repository, memberships)
    return db, repository, service, principal


def test_preferences_survive_sqlite_round_trip(tmp_path):
    _, repository, _, _ = make_owner_environment(tmp_path)

    preferences = OwnerLifestylePreferences(
        business_id="business-1",
        user_id="owner-1",
        timezone="Africa/Johannesburg",
        wake_time="06:00",
        sleep_time="22:00",
        briefing_time="07:15",
        initiative_level="balanced",
        personality="natural",
    )

    repository.save(preferences)
    loaded = repository.get("business-1", "owner-1")

    assert loaded is not None
    assert loaded.business_id == "business-1"
    assert loaded.user_id == "owner-1"
    assert loaded.timezone == "Africa/Johannesburg"
    assert loaded.wake_time == "06:00"
    assert loaded.sleep_time == "22:00"
    assert loaded.briefing_time == "07:15"
    assert loaded.initiative_level == "balanced"
    assert loaded.personality == "natural"


def test_owner_service_updates_persisted_preferences(tmp_path):
    _, repository, service, principal = make_owner_environment(tmp_path)

    updated = service.update_preferences(
        principal,
        "business-1",
        {
            "timezone": "Africa/Johannesburg",
            "wake_time": "06:30",
            "sleep_time": "22:30",
        },
    )

    loaded = repository.get("business-1", "owner-1")

    assert updated.wake_time == "06:30"
    assert loaded is not None
    assert loaded.wake_time == "06:30"
    assert loaded.sleep_time == "22:30"


def test_routine_suggestion_requires_explicit_acceptance(tmp_path):
    _, repository, service, principal = make_owner_environment(tmp_path)

    service.get_preferences(principal, "business-1")

    for _ in range(3):
        service.observe_routine(
            principal,
            "business-1",
            "wake_time",
            "06:15",
        )

    suggestions = service.list_pending_suggestions(
        principal, "business-1"
    )
    matching = [
        item for item in suggestions
        if item.field_name == "wake_time"
        and item.proposed_value == "06:15"
    ]

    assert matching, "Expected a pending wake-time suggestion."
    suggestion = matching[0]

    before = repository.get("business-1", "owner-1")
    assert before is not None
    assert before.wake_time != "06:15"

    service.resolve_suggestion(
        principal,
        "business-1",
        suggestion.suggestion_id,
        False,
    )

    after_rejection = repository.get("business-1", "owner-1")
    assert after_rejection is not None
    assert after_rejection.wake_time == before.wake_time

    # A rejected suggestion cannot be accepted a second time.
    import pytest
    with pytest.raises((LookupError, ValueError)):
        service.resolve_suggestion(
            principal,
            "business-1",
            suggestion.suggestion_id,
            True,
        )


def test_preferences_are_isolated_between_businesses(tmp_path):
    _, repository, _, _ = make_owner_environment(tmp_path)

    repository.save(
        OwnerLifestylePreferences(
            business_id="business-1",
            user_id="owner-1",
            wake_time="06:00",
        )
    )

    assert repository.get("business-2", "owner-1") is None
