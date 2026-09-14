from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import hashlib
import pytest

from app.auth.errors import AuthenticationError, AuthenticationRateLimited, BusinessSelectionRequired, SessionInvalid
from app.auth.passwords import ScryptPasswordHasher, ScryptPolicy
from app.auth.rate_limit import RateLimitPolicy, SQLiteAuthenticationRateLimiter
from app.auth.service import AuthenticationService
from app.auth.signup import SQLiteSignupTransaction, SignupConflict
from app.identity.models import BusinessMembership, User, UserRole
from app.models.business import Business
from app.persistence.business_repository import SQLiteBusinessRepository
from app.persistence.credential_repository import SQLiteCredentialRepository
from app.persistence.database import SCHEMA_VERSION, SQLiteDatabase
from app.persistence.membership_repository import SQLiteMembershipRepository
from app.persistence.session import SQLiteSessionRepository
from app.persistence.user_repository import SQLiteUserRepository

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def db(tmp_path):
    database = SQLiteDatabase(tmp_path / "assistant.sqlite3")
    database.initialize()
    return database


def seed(database):
    SQLiteUserRepository(database).save(User("u1", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(database).save(Business("b1", "Acme", "Owner", "Configured Test Assistant", "male"))
    SQLiteMembershipRepository(database).save(BusinessMembership("u1", "b1", UserRole.OWNER))
    SQLiteCredentialRepository(database).save("u1", ScryptPasswordHasher().hash("correct horse battery"), at=NOW)


def make_service(database, clock=lambda tz=None: NOW, rate=None):
    return AuthenticationService(
        SQLiteUserRepository(database),
        SQLiteCredentialRepository(database),
        SQLiteMembershipRepository(database),
        SQLiteSessionRepository(database),
        password_hasher=ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=1, dklen=32, maxmem=8*1024*1024, salt_bytes=16)),
        rate_limiter=rate,
        clock=clock,
    )


def test_scrypt_parameters_reach_hashlib_scrypt():
    hasher = ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=2, dklen=32, maxmem=8*1024*1024, salt_bytes=16))
    with patch("app.auth.passwords.hashlib.scrypt", wraps=hashlib.scrypt) as mocked:
        encoded = hasher.hash("a sufficiently long password")
    kwargs = mocked.call_args.kwargs
    assert kwargs["n"] == 2**10
    assert kwargs["r"] == 8
    assert kwargs["p"] == 2
    assert kwargs["dklen"] == 32
    assert kwargs["maxmem"] == 8*1024*1024
    assert hasher.verify("a sufficiently long password", encoded)


def test_login_retrieves_durable_credential_and_creates_hashed_session(tmp_path):
    database = db(tmp_path)
    hasher = ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=1, dklen=32, maxmem=8*1024*1024, salt_bytes=16))
    SQLiteUserRepository(database).save(User("u1", "Owner", "owner@example.com"))
    SQLiteBusinessRepository(database).save(Business("b1", "Acme", "Owner", "Configured Test Assistant", "male"))
    SQLiteMembershipRepository(database).save(BusinessMembership("u1", "b1", UserRole.OWNER))
    SQLiteCredentialRepository(database).save("u1", hasher.hash("correct horse battery"), at=NOW)
    service = AuthenticationService(
        SQLiteUserRepository(database), SQLiteCredentialRepository(database), SQLiteMembershipRepository(database), SQLiteSessionRepository(database), password_hasher=hasher, clock=lambda tz=None: NOW,
    )
    principal = service.login(" OWNER@example.com ", "correct horse battery", source_key="test")
    assert principal.user_id == "u1"
    assert principal.business_id == "b1"
    assert SQLiteSessionRepository(database).get(__import__("hashlib").sha256(principal.session_id.encode()).hexdigest()) is not None


def test_bad_password_is_generic_and_does_not_create_session(tmp_path):
    database = db(tmp_path)
    seed(database)
    service = make_service(database)
    with pytest.raises(AuthenticationError):
        service.login("owner@example.com", "wrong password", source_key="test")


def test_unknown_account_still_performs_password_verification(tmp_path):
    database = db(tmp_path)
    service = make_service(database)
    with patch.object(service._password_hasher, "verify", wraps=service._password_hasher.verify) as verify:
        with pytest.raises(AuthenticationError):
            service.login("missing@example.com", "wrong password", source_key="test")
    verify.assert_called_once()


def test_multiple_businesses_require_explicit_selection(tmp_path):
    database = db(tmp_path)
    seed(database)
    SQLiteBusinessRepository(database).save(Business("b2", "Second", "Owner", "Configured Test Assistant", "male"))
    SQLiteMembershipRepository(database).save(BusinessMembership("u1", "b2", UserRole.ADMIN))
    hasher = ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=1, dklen=32, maxmem=8*1024*1024, salt_bytes=16))
    SQLiteCredentialRepository(database).save("u1", hasher.hash("correct horse battery"), at=NOW)
    service = make_service(database)
    with pytest.raises(BusinessSelectionRequired):
        service.login("owner@example.com", "correct horse battery", source_key="test")
    principal = service.login("owner@example.com", "correct horse battery", business_id="b2", source_key="test")
    assert principal.business_id == "b2"


def test_rate_limit_persists_across_repository_instances(tmp_path):
    database = db(tmp_path)
    policy = RateLimitPolicy(failure_threshold=2, base_delay_seconds=60, max_delay_seconds=60, window_seconds=900)
    first = SQLiteAuthenticationRateLimiter(database, policy=policy, clock=lambda tz=None: NOW)
    first.record_failure("owner@example.com", "source")
    first.record_failure("owner@example.com", "source")
    second = SQLiteAuthenticationRateLimiter(database, policy=policy, clock=lambda tz=None: NOW)
    assert second.allow("owner@example.com", "source") is False


def test_rate_limit_success_resets_state(tmp_path):
    database = db(tmp_path)
    policy = RateLimitPolicy(failure_threshold=1, base_delay_seconds=60, max_delay_seconds=60, window_seconds=900)
    limiter = SQLiteAuthenticationRateLimiter(database, policy=policy, clock=lambda tz=None: NOW)
    limiter.record_failure("owner@example.com", "source")
    assert not limiter.allow("owner@example.com", "source")
    limiter.record_success("owner@example.com", "source")
    assert limiter.allow("owner@example.com", "source")


def test_signup_is_atomic_and_persists_all_required_records(tmp_path):
    database = db(tmp_path)
    hasher = ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=1, dklen=32, maxmem=8*1024*1024, salt_bytes=16))
    user, business, membership, started = SQLiteSignupTransaction(database, hasher, clock=lambda tz=None: NOW).signup(
        display_name="Owner", email="owner@example.com", password="correct horse battery", business_name="Acme", assistant_name="Configured Test Assistant", assistant_voice="male"
    )
    assert SQLiteUserRepository(database).get(user.user_id) == user
    assert SQLiteBusinessRepository(database).get(business.business_id) == business
    assert SQLiteMembershipRepository(database).get(user.user_id, business.business_id) == membership
    assert SQLiteCredentialRepository(database).get_by_user_id(user.user_id).credential_hash
    with database.connection() as connection:
        assert connection.execute("SELECT started_at FROM business_trials WHERE business_id = ?", (business.business_id,)).fetchone() is not None
        assert connection.execute("SELECT status FROM commercial_states WHERE business_id = ?", (business.business_id,)).fetchone()[0] == "trial"


def test_signup_rolls_back_everything_on_late_failure(tmp_path):
    database = db(tmp_path)
    with database.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_credential_insert BEFORE INSERT ON credentials BEGIN SELECT RAISE(ABORT, 'forced credential failure'); END"
        )
    with pytest.raises(Exception):
        SQLiteSignupTransaction(database, clock=lambda tz=None: NOW).signup(
            display_name="Owner", email="owner@example.com", password="correct horse battery", business_name="Acme", assistant_name="Configured Test Assistant", assistant_voice="male"
        )
    assert SQLiteUserRepository(database).get_by_email("owner@example.com") is None
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM business_memberships").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM business_trials").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM commercial_states").fetchone()[0] == 0


def test_schema_migrates_legacy_v1_to_current_schema(tmp_path):
    path = tmp_path / "assistant.sqlite3"
    connection = __import__("sqlite3").connect(path)
    connection.executescript(
        __import__("app.persistence.database", fromlist=["BASE_SCHEMA"]).BASE_SCHEMA
    )
    connection.execute(
        "INSERT INTO persistence_metadata(key, value) VALUES('schema_version', '1')"
    )
    connection.commit()
    connection.close()

    database = SQLiteDatabase(path)
    database.initialize()

    with database.connection() as connection:
        assert (
            connection.execute(
                "SELECT value FROM persistence_metadata "
                "WHERE key='schema_version'"
            ).fetchone()[0]
            == str(SCHEMA_VERSION)
        )

        # v1 -> v2 migration
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='credentials'"
        ).fetchone() is not None

        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='auth_throttle_state'"
        ).fetchone() is not None

        # v2 -> v3 migration
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='whatsapp_bindings'"
        ).fetchone() is not None

        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='whatsapp_inbound_messages'"
        ).fetchone() is not None

        # v3 -> v4 migration
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='whatsapp_conversation_turns'"
        ).fetchone() is not None


def test_session_expiration_invalidates_and_revokes(tmp_path):
    database = db(tmp_path)
    seed(database)
    service = make_service(database, clock=lambda tz=None: NOW + timedelta(hours=13))
    principal = AuthenticationService(
        SQLiteUserRepository(database), SQLiteCredentialRepository(database), SQLiteMembershipRepository(database), SQLiteSessionRepository(database), password_hasher=ScryptPasswordHasher(ScryptPolicy(n=2**10, r=8, p=1, dklen=32, maxmem=8*1024*1024, salt_bytes=16)), clock=lambda tz=None: NOW,
    ).login("owner@example.com", "correct horse battery", source_key="test")
    with pytest.raises(SessionInvalid):
        service.validate_session(principal.session_id)
