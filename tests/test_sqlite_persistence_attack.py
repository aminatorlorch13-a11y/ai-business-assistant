from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.commercial.purchase import VerifiedPurchase
from app.commercial.purchase_application import CommercialPurchaseService
from app.identity import BusinessMembership, SessionScope, UserRole
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
    session = SessionRecord("hash", "u", SessionScope.BUSINESS, "b", UserRole.OWNER, NOW, NOW, NOW)
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


def test_session_scope_constraints_reject_invalid_combinations(tmp_path):
    db = make_db(tmp_path)

    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, display_name, email)
            VALUES (?, ?, ?)
            """,
            ("scope-user", "Scope User", "scope-user@example.test"),
        )
        connection.execute(
            """
            INSERT INTO businesses(
                business_id,
                name,
                owner_name,
                assistant_name,
                assistant_voice
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "scope-business",
                "Scope Business",
                "Scope Owner",
                "Scope Assistant",
                "calm",
            ),
        )

        base = (
            "scope-hash",
            "scope-user",
            "2026-01-01T12:00:00+00:00",
            "2026-01-01T13:00:00+00:00",
            "2026-01-01T12:00:00+00:00",
        )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id_hash,
                    user_id,
                    scope,
                    business_id,
                    role,
                    created_at,
                    expires_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    base[0],
                    base[1],
                    "business",
                    None,
                    "owner",
                    base[2],
                    base[3],
                    base[4],
                ),
            )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id_hash,
                    user_id,
                    scope,
                    business_id,
                    role,
                    created_at,
                    expires_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "scope-hash-platform-business",
                    base[1],
                    "platform",
                    "scope-business",
                    None,
                    base[2],
                    base[3],
                    base[4],
                ),
            )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id_hash,
                    user_id,
                    scope,
                    business_id,
                    role,
                    created_at,
                    expires_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "scope-hash-platform-role",
                    base[1],
                    "platform",
                    None,
                    "owner",
                    base[2],
                    base[3],
                    base[4],
                ),
            )

        with pytest.raises(Exception):
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id_hash,
                    user_id,
                    scope,
                    business_id,
                    role,
                    created_at,
                    expires_at,
                    last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "scope-hash-business-role",
                    base[1],
                    "business",
                    "scope-business",
                    "invalid-role",
                    base[2],
                    base[3],
                    base[4],
                ),
            )

        connection.execute(
            """
            INSERT INTO sessions(
                session_id_hash,
                user_id,
                scope,
                business_id,
                role,
                created_at,
                expires_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "scope-hash-valid-platform",
                base[1],
                "platform",
                None,
                None,
                base[2],
                base[3],
                base[4],
            ),
        )


def test_memory_id_cannot_be_taken_over_by_another_business(tmp_path):
    db = make_db(tmp_path)
    businesses = SQLiteBusinessRepository(db)
    businesses.save(make_business("a"))
    businesses.save(make_business("b"))
    repo = SQLiteMemoryRepository(db)

    original = Memory("shared-id", "a", "secret-a", "business_rule", 5)
    repo.save(original)

    with pytest.raises(ValueError, match="already belongs"):
        repo.save(Memory("shared-id", "b", "stolen", "business_rule", 1))

    assert repo.get("shared-id") == original
    assert repo.list_for_business("a") == [original]
    assert repo.list_for_business("b") == []


def test_memory_owner_can_update_existing_memory(tmp_path):
    db = make_db(tmp_path)
    SQLiteBusinessRepository(db).save(make_business("a"))
    repo = SQLiteMemoryRepository(db)

    repo.save(Memory("owned-id", "a", "before", "business_rule", 2))
    updated = Memory("owned-id", "a", "after", "business_rule", 4)

    assert repo.save(updated) == updated
    assert repo.get("owned-id") == updated
