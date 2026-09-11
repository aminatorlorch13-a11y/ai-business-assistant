from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_application import CommercialPurchaseService
from app.identity import BusinessMembership, UserRole
from app.models.business import Business
from app.models.memory import Memory
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.commercial_transaction_factory import SQLiteCommercialTransactionFactory
from app.persistence.database import SQLiteDatabase
from app.persistence.memory_repository import SQLiteMemoryRepository
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SessionRecord, SQLiteSessionRepository
from app.persistence.trial_repository import SQLiteTrialRepository

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def make_db(tmp_path):
    db = SQLiteDatabase(tmp_path / "attack.sqlite3")
    db.initialize()
    return db


def make_business(business_id):
    return Business(business_id, business_id, "Owner", "Configured Test Assistant", "female")


def test_cross_tenant_memory_filter_is_enforced_at_repository_boundary(tmp_path):
    db = make_db(tmp_path)
    businesses = SQLiteBusinessRepository(db)
    businesses.save(make_business("a"))
    businesses.save(make_business("b"))
    repo = SQLiteMemoryRepository(db)
    repo.save(Memory("m-a", "a", "secret-a", "business_rule", 5))
    repo.save(Memory("m-b", "b", "secret-b", "business_rule", 5))
    assert [m.memory_id for m in repo.list_for_business("a")] == ["m-a"]


def test_membership_parent_integrity_blocks_orphan_authorization(tmp_path):
    with pytest.raises(Exception):
        SQLiteMembershipRepository(make_db(tmp_path)).save(BusinessMembership("u", "b", UserRole.OWNER))


def test_trial_parent_integrity_blocks_orphan_trial(tmp_path):
    from app.commercial.trial import BusinessTrial
    with pytest.raises(Exception):
        SQLiteTrialRepository(make_db(tmp_path)).save(BusinessTrial("missing", NOW))


def test_session_parent_integrity_blocks_orphan_session(tmp_path):
    db = make_db(tmp_path)
    session = SessionRecord("hash", "u", "b", UserRole.OWNER, NOW, NOW, NOW)
    with pytest.raises(Exception):
        SQLiteSessionRepository(db).save(session)


def test_commercial_transaction_rolls_back_purchase_when_activation_fails(tmp_path):
    db = make_db(tmp_path)
    SQLiteBusinessRepository(db).save(make_business("b"))
    with db.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_activation BEFORE INSERT ON commercial_states "
            "BEGIN SELECT RAISE(ABORT, 'forced activation failure'); END"
        )
    purchase = VerifiedPurchase("provider", "event", "b", Decimal("25.00"), "ZAR", NOW)
    with pytest.raises(Exception):
        CommercialPurchaseService(SQLiteCommercialTransactionFactory(db)).process(purchase, NOW)
    with db.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM purchase_records").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM commercial_states").fetchone()[0] == 0
