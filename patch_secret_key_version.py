from pathlib import Path
import shutil

service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

for path in (service_path, test_path):
    backup = path.with_name(path.name + ".pre_key_version.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

service = service_path.read_text()
old = '''        ciphertext, _version = self.repository.get_encrypted_secret(
            connection_id=connection_id, business_id=business_id, user_id=user_id,
        )
        payload = json.loads(self.cipher.decrypt(ciphertext).decode("utf-8"))
'''
new = '''        ciphertext, stored_version = self.repository.get_encrypted_secret(
            connection_id=connection_id, business_id=business_id, user_id=user_id,
        )
        expected_version = getattr(self.cipher, "key_version", None)
        if expected_version is not None and stored_version != expected_version:
            raise RuntimeError("Stored integration secret uses an unsupported key version.")
        payload = json.loads(self.cipher.decrypt(ciphertext).decode("utf-8"))
'''
if old in service:
    service = service.replace(old, new, 1)
elif "stored_version = self.repository.get_encrypted_secret(" not in service:
    raise SystemExit("Could not find the expected secret-decryption block.")

tests = test_path.read_text()
test_name = "test_unknown_secret_key_version_fails_closed"

if test_name not in tests:
    tests += '''

def test_unknown_secret_key_version_fails_closed(integration_setup):
    database, service, connection_id = integration_setup

    with database.transaction() as db:
        db.execute(
            "UPDATE integration_secrets SET key_version = ? "
            "WHERE connection_id = ?",
            ("unknown-key-v99", connection_id),
        )

    with pytest.raises(RuntimeError, match="unsupported key version"):
        service.read_secret_payload(
            connection_id=connection_id,
            business_id="business-a",
            user_id="user-a",
        )
'''
    test_path.write_text(tests)

service_path.write_text(service)
print("Key-version validation patch applied.")
