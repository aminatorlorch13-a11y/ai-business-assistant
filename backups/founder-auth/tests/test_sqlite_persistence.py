from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_record import PurchaseRecord
from app.commercial.trial import BusinessTrial
from app.identity import BusinessMembership, User, UserRole
from app.models.business import Business
from app.models.memory import Memory
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_repository import SQLitePurchaseStore
from app.persistence.commercial_state_repository import SQLiteCommercialStateRepository
from app.persistence.commercial_transaction_factory import SQLiteCommercialTransactionFactory
from app.persistence.database import SQLiteDatabase
from app.persistence.launch_repository import SQLiteLaunchProgramRepository
from app.persistence.memory_repository import SQLiteMemoryRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SessionRecord, SQLiteSessionRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.persistence.user_repository import SQLiteUserRepository
from app.persistence.trial_repository import SQLiteTrialRepository
from app.commercial.purchase_application import CommercialPurchaseService

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_database(tmp_path):
    db = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    db.initialize()
    return db


def make_business(business_id="business-1"):
    return Business(business_id, "Acme", "Owner", "Configured Test Assistant", "male")


def test_schema_and_business_survive_restart(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLiteBusinessRepository(reopened).get("business-1") == make_business()


def test_user_email_unique_case_insensitively(tmp_path):
    db = make_database(tmp_path)
    repo = SQLiteUserRepository(db)
    repo.save(User("u1", "One", "Owner@example.com"))
    with pytest.raises(Exception):
        repo.save(User("u2", "Two", "owner@EXAMPLE.com"))


def test_membership_requires_existing_parents(tmp_path):
    db = make_database(tmp_path)
    with pytest.raises(Exception):
        SQLiteMembershipRepository(db).save(BusinessMembership("u", "b", UserRole.OWNER))
    SQLiteUserRepository(db).save(User("u", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(db).save(make_business("b"))
    membership = BusinessMembership("u", "b", UserRole.OWNER)
    assert SQLiteMembershipRepository(db).save(membership) == membership


def test_memory_round_trip_and_tenant_filter(tmp_path):
    db = make_database(tmp_path)
    businesses = SQLiteBusinessRepository(db)
    businesses.save(make_business("a"))
    businesses.save(make_business("b"))
    repo = SQLiteMemoryRepository(db)
    first = Memory("m-a", "a", "secret-a", "business_rule", 5)
    second = Memory("m-b", "b", "secret-b", "business_rule", 5)
    repo.save(first)
    repo.save(second)
    assert repo.get("m-a") == first
    assert repo.list_for_business("a") == [first]
    assert repo.delete("m-a") is True


def test_memory_cannot_reference_unknown_business(tmp_path):
    db = make_database(tmp_path)
    with pytest.raises(ValueError):
        SQLiteMemoryRepository(db).save(Memory("m", "missing", "no", "business_rule", 1))


def test_trial_start_survives_restart(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    trial = BusinessTrial("business-1", NOW)
    SQLiteTrialRepository(db).save(trial)
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLiteTrialRepository(reopened).get("business-1") == trial


def test_session_round_trip_and_immediate_revoke(tmp_path):
    db = make_database(tmp_path)
    SQLiteUserRepository(db).save(User("u", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(db).save(make_business("b"))
    session = SessionRecord("hash", "u", "b", UserRole.OWNER, NOW, NOW + timedelta(hours=1), NOW)
    repo = SQLiteSessionRepository(db)
    assert repo.save(session) == session
    assert repo.get("hash") == session
    assert repo.revoke("hash", NOW + timedelta(minutes=1)) is True
    assert repo.revoke("hash", NOW + timedelta(minutes=2)) is False


def test_purchase_history_survives_restart_and_is_unique(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    purchase = VerifiedPurchase("provider", "event", "business-1", Decimal("100.00"), "ZAR", NOW)
    record = PurchaseRecord(purchase, NOW)
    repo = SQLitePurchaseStore(db)
    repo.save(record)
    with pytest.raises(ValueError):
        repo.save(record)
    reopened = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    reopened.initialize()
    assert SQLitePurchaseStore(reopened).get("provider", "event") == record


def test_commercial_purchase_is_atomic_and_paid_business_is_counted_once(tmp_path):
    db = make_database(tmp_path)
    SQLiteBusinessRepository(db).save(make_business())
    service = CommercialPurchaseService(SQLiteCommercialTransactionFactory(db))
    purchase = VerifiedPurchase("provider", "event-1", "business-1", Decimal("25.00"), "ZAR", NOW)
    assert service.process(purchase, NOW).processed is True
    assert SQLiteCommercialStateRepository(db).get("business-1").status.value == "active"
    assert SQLiteLaunchProgramRepository(db).get().paid_businesses == 1
    assert service.process(purchase, NOW).duplicate is True
    assert SQLiteLaunchProgramRepository(db).get().paid_businesses == 1
