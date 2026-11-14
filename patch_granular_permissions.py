from pathlib import Path
import shutil

repo_path = Path("app/persistence/integration_repository.py")
service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

for path in (repo_path, service_path, test_path):
    backup = path.with_name(path.name + ".pre_granular_permissions.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

repo = repo_path.read_text()
anchor = "    def revoke_connection(\n"

method = '''    def revoke_permission(
        self, *, connection_id: str, business_id: str, user_id: str,
        scope: str,
    ) -> None:
        permission_scope = _required(scope, "scope")
        timestamp = _now()

        with self.database.transaction() as db:
            connection = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()

            if connection is None:
                raise PermissionError("Active tenant-owned connection not found.")

            updated = db.execute("""
                UPDATE integration_permissions
                SET revoked_at = ?
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND scope = ? AND revoked_at IS NULL
            """, (
                timestamp, connection_id, business_id, user_id,
                permission_scope,
            ))

            if updated.rowcount != 1:
                raise PermissionError("Active permission not found.")

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'permission_revoked', ?, ?)
            """, (
                str(uuid4()), business_id, user_id, connection_id, timestamp,
                json.dumps({
                    "provider": connection["provider"],
                    "scope": permission_scope,
                }),
            ))

'''

if "def revoke_permission(" not in repo:
    if anchor not in repo:
        raise SystemExit("Repository insertion point not found.")
    repo = repo.replace(anchor, method + anchor, 1)

service = service_path.read_text()
anchor = "    def revoke(\n"

method = '''    def revoke_permission(
        self, *, connection_id: str, business_id: str, user_id: str,
        scope: str,
    ) -> None:
        self.repository.revoke_permission(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            scope=scope,
        )

'''

if "    def revoke_permission(" not in service:
    if anchor not in service:
        raise SystemExit("Service insertion point not found.")
    service = service.replace(anchor, method + anchor, 1)

tests = test_path.read_text()
name = "test_permission_can_be_revoked_without_disconnecting_account"

if name not in tests:
    tests += '''

def test_permission_can_be_revoked_without_disconnecting_account(tmp_path):
    database = SQLiteDatabase(tmp_path / "permission-revocation.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    connection_id = service.connect(
        business_id="business-permissions",
        user_id="user-permissions",
        provider="gmail",
        external_account_id="google-permissions",
        scopes={"email.read", "email.send"},
        secret_payload={"access_token": "permission-test-secret"},
        consent_confirmed=True,
    )

    service.revoke_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.send",
    )

    assert service.has_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.read",
    )
    assert not service.has_permission(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
        scope="email.send",
    )

    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-permissions",
        user_id="user-permissions",
    ) == {"access_token": "permission-test-secret"}

    with database.connection() as db:
        event = db.execute(
            "SELECT details_json FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'permission_revoked'",
            (connection_id,),
        ).fetchone()

    assert event is not None
    assert '"scope": "email.send"' in event["details_json"]
'''

    test_path.write_text(tests)

repo_path.write_text(repo)
service_path.write_text(service)
print("Granular permission revocation added. Backups created.")
