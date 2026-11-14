from pathlib import Path
import shutil

test_path = Path("tests/test_integrations.py")
backup = test_path.with_name(
    test_path.name + ".pre_integrity_tests.bak"
)

if not backup.exists():
    shutil.copy2(test_path, backup)

tests = test_path.read_text()

additions = '''

def test_other_user_cannot_revoke_connection_permission(tmp_path):
    database = SQLiteDatabase(tmp_path / "permission-owner.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="shared-business",
        user_id="connection-owner",
        provider="gmail",
        external_account_id="google-owner",
        scopes={"email.read", "email.send"},
        secret_payload={"access_token": "owner-secret"},
        consent_confirmed=True,
    )

    with pytest.raises(PermissionError):
        service.revoke_permission(
            connection_id=connection_id,
            business_id="shared-business",
            user_id="different-user",
            scope="email.send",
        )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="shared-business",
        user_id="connection-owner",
        scope="email.send",
    )

    with database.connection() as db:
        events = db.execute(
            "SELECT COUNT(*) FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()[0]

    assert events == 0


def test_permission_cannot_be_revoked_twice(tmp_path):
    database = SQLiteDatabase(tmp_path / "repeat-revoke.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="repeat-business",
        user_id="repeat-user",
        provider="gmail",
        external_account_id="google-repeat",
        scopes={"email.read"},
        secret_payload={"access_token": "repeat-secret"},
        consent_confirmed=True,
    )

    arguments = {
        "connection_id": connection_id,
        "business_id": "repeat-business",
        "user_id": "repeat-user",
        "scope": "email.read",
    }

    service.revoke_permission(**arguments)

    with pytest.raises(PermissionError):
        service.revoke_permission(**arguments)

    with database.connection() as db:
        events = db.execute(
            "SELECT COUNT(*) FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()[0]

    assert events == 1


def test_integration_schema_has_no_foreign_key_violations(tmp_path):
    database = SQLiteDatabase(tmp_path / "foreign-keys.sqlite3")
    database.initialize()

    with database.connection() as db:
        violations = db.execute("PRAGMA foreign_key_check").fetchall()

    assert violations == []
'''

names = (
    "test_other_user_cannot_revoke_connection_permission",
    "test_permission_cannot_be_revoked_twice",
    "test_integration_schema_has_no_foreign_key_violations",
)

missing = [name for name in names if name not in tests]

if missing:
    tests += additions
    test_path.write_text(tests)

print("Integration integrity tests added. Backup preserved.")
