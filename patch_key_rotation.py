from pathlib import Path
import shutil

security_path = Path("app/integrations/security.py")
service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

for path in (security_path, service_path, test_path):
    backup = path.with_name(path.name + ".pre_key_rotation.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

security = security_path.read_text()

if "class FernetKeyringCipher:" not in security:
    security = security.replace(
        "from typing import Protocol",
        "from typing import Protocol\nfrom collections.abc import Mapping",
        1,
    )
    security += '''

class FernetKeyringCipher:
    """Encrypt with the active key and decrypt with approved historical keys."""

    def __init__(
        self, keys: Mapping[str, str | bytes], active_version: str,
    ) -> None:
        from cryptography.fernet import Fernet

        if not isinstance(keys, Mapping) or not keys:
            raise ValueError("At least one encryption key is required.")
        if not isinstance(active_version, str) or active_version not in keys:
            raise ValueError("The active encryption key version is not configured.")

        self._fernets = {}
        for version, key in keys.items():
            if not isinstance(version, str) or not version.strip():
                raise ValueError("Encryption key versions must be non-empty strings.")
            try:
                raw_key = key.encode() if isinstance(key, str) else key
                self._fernets[version] = Fernet(raw_key)
            except Exception as exc:
                raise ValueError(
                    f"Invalid encryption key for version {version!r}."
                ) from exc

        self.key_version = active_version

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ValueError("Secret payload must be non-empty bytes.")
        return self._fernets[self.key_version].encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self.decrypt_for_version(ciphertext, self.key_version)

    def decrypt_for_version(self, ciphertext: bytes, version: str) -> bytes:
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted payload must be non-empty bytes.")
        fernet = self._fernets.get(version)
        if fernet is None:
            raise RuntimeError("Stored integration secret uses an unsupported key version.")
        try:
            return fernet.decrypt(ciphertext)
        except Exception as exc:
            raise RuntimeError(
                "Integration secret could not be authenticated."
            ) from exc
'''
    security_path.write_text(security)

service = service_path.read_text()
old = '''        expected_version = getattr(self.cipher, "key_version", None)
        if expected_version is not None and stored_version != expected_version:
            raise RuntimeError("Stored integration secret uses an unsupported key version.")
        payload = json.loads(self.cipher.decrypt(ciphertext).decode("utf-8"))
'''
new = '''        decrypt_for_version = getattr(self.cipher, "decrypt_for_version", None)
        if callable(decrypt_for_version):
            plaintext = decrypt_for_version(ciphertext, stored_version)
        else:
            expected_version = getattr(self.cipher, "key_version", None)
            if expected_version is not None and stored_version != expected_version:
                raise RuntimeError(
                    "Stored integration secret uses an unsupported key version."
                )
            plaintext = self.cipher.decrypt(ciphertext)

        payload = json.loads(plaintext.decode("utf-8"))
'''
if old in service:
    service = service.replace(old, new, 1)
elif "decrypt_for_version(ciphertext, stored_version)" not in service:
    raise SystemExit("Secret decryption block not found.")

if "    def rotate_secret(" not in service:
    service += '''

    def rotate_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> None:
        """Re-encrypt one owned secret using the currently active key."""
        payload = self.read_secret_payload(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
        )
        ciphertext = self.cipher.encrypt(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        self.repository.save_encrypted_secret(
            connection_id=connection_id,
            business_id=business_id,
            ciphertext=ciphertext,
            key_version=getattr(self.cipher, "key_version", "custom"),
        )
'''
service_path.write_text(service)

tests = test_path.read_text()
test_name = "test_old_secret_can_be_read_and_rotated_to_active_key"

if test_name not in tests:
    tests += '''

def test_old_secret_can_be_read_and_rotated_to_active_key(tmp_path):
    from app.integrations.security import FernetKeyringCipher

    database = SQLiteDatabase(tmp_path / "key-rotation.sqlite3")
    database.initialize()

    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    keyring = FernetKeyringCipher(
        keys={"fernet-v1": old_key, "fernet-v2": new_key},
        active_version="fernet-v2",
    )
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, keyring)

    connection_id = service.connect(
        business_id="business-rotation",
        user_id="user-rotation",
        provider="gmail",
        external_account_id="google-rotation",
        scopes={"email.read"},
        secret_payload={"access_token": "rotation-test-secret"},
        consent_confirmed=True,
    )

    old_cipher = FernetSecretCipher(old_key)
    old_ciphertext = old_cipher.encrypt(
        b'{"access_token":"rotation-test-secret"}'
    )
    repository.save_encrypted_secret(
        connection_id=connection_id,
        business_id="business-rotation",
        ciphertext=old_ciphertext,
        key_version="fernet-v1",
    )

    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    ) == {"access_token": "rotation-test-secret"}

    service.rotate_secret(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    )

    with database.connection() as db:
        row = db.execute(
            "SELECT encrypted_payload, key_version FROM integration_secrets "
            "WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()

    assert row["key_version"] == "fernet-v2"
    assert bytes(row["encrypted_payload"]) != old_ciphertext
    assert service.read_secret_payload(
        connection_id=connection_id,
        business_id="business-rotation",
        user_id="user-rotation",
    ) == {"access_token": "rotation-test-secret"}
'''
    test_path.write_text(tests)

print("Key rotation patch applied. Backups created.")
