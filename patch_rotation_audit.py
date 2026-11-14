from pathlib import Path
import shutil

repo_path = Path("app/persistence/integration_repository.py")
service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

for path in (repo_path, service_path, test_path):
    backup = path.with_name(path.name + ".pre_rotation_audit.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

repo = repo_path.read_text()
anchor = "    def get_connection(\n"

method = '''    def rotate_encrypted_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
        ciphertext: bytes, old_key_version: str, new_key_version: str,
    ) -> None:
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted secret is required.")
        old_version = _required(old_key_version, "old_key_version")
        new_version = _required(new_key_version, "new_key_version")
        timestamp = _now()

        with self.database.transaction() as db:
            owner = db.execute("""
                SELECT provider FROM integration_connections
                WHERE connection_id = ? AND business_id = ?
                  AND user_id = ? AND status = 'active'
            """, (connection_id, business_id, user_id)).fetchone()

            if owner is None:
                raise PermissionError("Active tenant-owned connection not found.")

            updated = db.execute("""
                UPDATE integration_secrets
                SET encrypted_payload = ?, key_version = ?, updated_at = ?
                WHERE connection_id = ? AND business_id = ?
                  AND key_version = ?
            """, (
                ciphertext, new_version, timestamp,
                connection_id, business_id, old_version,
            ))

            if updated.rowcount != 1:
                raise RuntimeError(
                    "Secret changed during rotation; reload it before retrying."
                )

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'secret_rotated', ?, ?)
            """, (
                str(uuid4()), business_id, user_id, connection_id, timestamp,
                json.dumps({
                    "provider": owner["provider"],
                    "old_key_version": old_version,
                    "new_key_version": new_version,
                }),
            ))

'''

if "def rotate_encrypted_secret(" not in repo:
    if anchor not in repo:
        raise SystemExit("Repository insertion point not found.")
    repo = repo.replace(anchor, method + anchor, 1)

service = service_path.read_text()
start = service.find("    def rotate_secret(")
if start == -1:
    raise SystemExit("rotate_secret method not found.")

replacement = '''    def rotate_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> None:
        """Re-encrypt one owned secret and audit the rotation atomically."""
        ciphertext, old_version = self.repository.get_encrypted_secret(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
        )

        decrypt_for_version = getattr(self.cipher, "decrypt_for_version", None)
        if callable(decrypt_for_version):
            plaintext = decrypt_for_version(ciphertext, old_version)
        else:
            expected_version = getattr(self.cipher, "key_version", None)
            if expected_version is not None and old_version != expected_version:
                raise RuntimeError(
                    "Stored integration secret uses an unsupported key version."
                )
            plaintext = self.cipher.decrypt(ciphertext)

        new_ciphertext = self.cipher.encrypt(plaintext)
        new_version = getattr(self.cipher, "key_version", "custom")

        self.repository.rotate_encrypted_secret(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            ciphertext=new_ciphertext,
            old_key_version=old_version,
            new_key_version=new_version,
        )
'''

service = service[:start] + replacement + "\n"
tests = test_path.read_text()

# Extend the existing successful rotation test with audit verification.
needle = '''    assert row["key_version"] == "fernet-v2"
    assert bytes(row["encrypted_payload"]) != old_ciphertext
'''
addition = '''    assert row["key_version"] == "fernet-v2"
    assert bytes(row["encrypted_payload"]) != old_ciphertext

    with database.connection() as db:
        audit = db.execute(
            "SELECT event_type, details_json FROM integration_audit_events "
            "WHERE connection_id = ? AND event_type = 'secret_rotated'",
            (connection_id,),
        ).fetchone()

    assert audit is not None
    assert '"old_key_version": "fernet-v1"' in audit["details_json"]
    assert '"new_key_version": "fernet-v2"' in audit["details_json"]
'''
if needle in tests and "secret_rotated" not in tests:
    tests = tests.replace(needle, addition, 1)

test_name = "test_rotation_rejects_stale_key_version"
if test_name not in tests:
    tests += '''

def test_rotation_rejects_stale_key_version(integration_setup):
    database, service, connection_id = integration_setup
    repository = service.repository
    cipher = service.cipher

    ciphertext, current_version = repository.get_encrypted_secret(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    )

    with pytest.raises(RuntimeError, match="changed during rotation"):
        repository.rotate_encrypted_secret(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
            ciphertext=cipher.encrypt(b'{"access_token":"stale"}'),
            old_key_version="stale-version",
            new_key_version=current_version,
        )

    assert repository.get_encrypted_secret(
        connection_id=connection_id,
        business_id="business-a",
        user_id="user-a",
    ) == (ciphertext, current_version)
'''
    test_path.write_text(tests)

repo_path.write_text(repo)
service_path.write_text(service)
print("Rotation audit and stale-write protection applied.")
