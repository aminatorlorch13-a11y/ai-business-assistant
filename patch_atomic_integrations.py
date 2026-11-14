from pathlib import Path
import shutil

repo_path = Path("app/persistence/integration_repository.py")
service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

for path in (repo_path, service_path, test_path):
    backup = path.with_name(path.name + ".pre_atomic.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

repo = repo_path.read_text()
anchor = "    def save_encrypted_secret(\n"
method = '''    def create_connection_with_secret(
        self, *, connection_id: str, business_id: str, user_id: str,
        provider: str, external_account_id: str, scopes: set[str],
        ciphertext: bytes, key_version: str,
    ) -> None:
        values = (
            _required(connection_id, "connection_id"),
            _required(business_id, "business_id"),
            _required(user_id, "user_id"),
            _required(provider, "provider"),
            _required(external_account_id, "external_account_id"),
        )
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted secret is required.")
        version = _required(key_version, "key_version")
        timestamp = _now()

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO integration_connections(
                    connection_id, business_id, user_id, provider,
                    external_account_id, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?)
            """, (*values, timestamp))

            for scope in sorted(scopes):
                db.execute("""
                    INSERT INTO integration_permissions(
                        permission_id, connection_id, business_id, user_id,
                        scope, granted_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid4()), values[0], values[1], values[2],
                    scope, timestamp,
                ))

            db.execute("""
                INSERT INTO integration_secrets(
                    connection_id, business_id, encrypted_payload,
                    key_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
            """, (values[0], values[1], ciphertext, version, timestamp))

            db.execute("""
                INSERT INTO integration_audit_events(
                    event_id, business_id, user_id, connection_id,
                    event_type, created_at, details_json
                ) VALUES (?, ?, ?, ?, 'connection_created', ?, ?)
            """, (
                str(uuid4()), values[1], values[2], values[0], timestamp,
                json.dumps({"provider": values[3], "scopes": sorted(scopes)}),
            ))

'''

if "def create_connection_with_secret(" not in repo:
    if anchor not in repo:
        raise SystemExit("Repository insertion point not found.")
    repo = repo.replace(anchor, method + anchor, 1)

service = service_path.read_text()
old = '''        self.repository.create_connection(
            connection_id=connection_id, business_id=business_id,
            user_id=user_id, provider=provider,
            external_account_id=external_account_id, scopes=set(scopes),
        )
        self.repository.save_encrypted_secret(
            connection_id=connection_id, business_id=business_id,
            ciphertext=ciphertext, key_version=getattr(
                self.cipher, "key_version", "custom"
            ),
        )
'''
new = '''        self.repository.create_connection_with_secret(
            connection_id=connection_id, business_id=business_id,
            user_id=user_id, provider=provider,
            external_account_id=external_account_id, scopes=set(scopes),
            ciphertext=ciphertext,
            key_version=getattr(self.cipher, "key_version", "custom"),
        )
'''
if old in service:
    service = service.replace(old, new, 1)
elif "self.repository.create_connection_with_secret(" not in service:
    raise SystemExit("Service call block not found.")

tests = test_path.read_text()
test = '''

def test_connection_creation_rolls_back_everything_if_secret_insert_fails(tmp_path):
    database = SQLiteDatabase(tmp_path / "atomic-integrations.sqlite3")
    database.initialize()
    cipher = FernetSecretCipher(Fernet.generate_key())
    repository = SQLiteIntegrationRepository(database)
    service = IntegrationService(repository, cipher)

    with database.transaction() as db:
        db.execute("""
            CREATE TRIGGER force_secret_insert_failure
            BEFORE INSERT ON integration_secrets
            BEGIN
                SELECT RAISE(ABORT, 'forced secret insert failure');
            END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="forced secret insert failure"):
        service.connect(
            business_id="business-atomic",
            user_id="user-atomic",
            provider="gmail",
            external_account_id="google-atomic",
            scopes={"email.read"},
            secret_payload={"access_token": "must-not-be-stored"},
            consent_confirmed=True,
        )

    with database.connection() as db:
        for table in (
            "integration_connections",
            "integration_permissions",
            "integration_secrets",
            "integration_audit_events",
        ):
            assert db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE business_id = ?",
                ("business-atomic",),
            ).fetchone()[0] == 0
'''

if "test_connection_creation_rolls_back_everything_if_secret_insert_fails" not in tests:
    tests += test

repo_path.write_text(repo)
service_path.write_text(service)
test_path.write_text(tests)
print("Atomic patch applied. Backups created.")
