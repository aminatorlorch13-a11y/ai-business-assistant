from pathlib import Path
import shutil

database_path = Path("app/persistence/database.py")
repo_path = Path("app/persistence/integration_repository.py")
service_path = Path("app/integrations/service.py")
test_path = Path("tests/test_integrations.py")

paths = (database_path, repo_path, service_path, test_path)

for path in paths:
    backup = path.with_name(path.name + ".pre_oauth_foundation.bak")
    if not backup.exists():
        shutil.copy2(path, backup)

# 1. Database migration 26
database = database_path.read_text()

if "def _migrate_v25_to_v26(" not in database:
    database = database.replace(
        "SCHEMA_VERSION = 25",
        "SCHEMA_VERSION = 26",
        1,
    )

    anchor = "MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {"

    migration = '''def _migrate_v25_to_v26(connection: sqlite3.Connection) -> None:
    """Store short-lived, single-use OAuth authorisation attempts."""
    connection.execute("""
        CREATE TABLE oauth_authorization_attempts (
            state_hash TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            redirect_uri TEXT NOT NULL,
            encrypted_code_verifier BLOB NOT NULL,
            key_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        )
    """)
    connection.execute("""
        CREATE INDEX idx_oauth_attempts_owner
        ON oauth_authorization_attempts(
            business_id, user_id, provider, expires_at
        )
    """)


'''

    if anchor not in database:
        raise SystemExit("Migration registry insertion point not found.")

    database = database.replace(anchor, migration + anchor, 1)

    registry_anchor = "    24: _migrate_v24_to_v25,"
    if registry_anchor not in database:
        raise SystemExit("Migration 24 registry entry not found.")

    database = database.replace(
        registry_anchor,
        registry_anchor + "\n    25: _migrate_v25_to_v26,",
        1,
    )

    database_path.write_text(database)

# 2. OAuth repository methods
repo = repo_path.read_text()

if "    def create_oauth_attempt(" not in repo:
    anchor = "    def create_connection(\n"

    methods = '''    def create_oauth_attempt(
        self, *, state_hash: str, business_id: str, user_id: str,
        provider: str, redirect_uri: str,
        encrypted_code_verifier: bytes, key_version: str,
        created_at: str, expires_at: str,
    ) -> None:
        values = (
            _required(state_hash, "state_hash"),
            _required(business_id, "business_id"),
            _required(user_id, "user_id"),
            _required(provider, "provider"),
            _required(redirect_uri, "redirect_uri"),
            encrypted_code_verifier,
            _required(key_version, "key_version"),
            _required(created_at, "created_at"),
            _required(expires_at, "expires_at"),
        )

        if not isinstance(encrypted_code_verifier, bytes) or not encrypted_code_verifier:
            raise ValueError("Encrypted PKCE verifier is required.")

        if expires_at <= created_at:
            raise ValueError("OAuth attempt expiry must be after creation.")

        with self.database.transaction() as db:
            db.execute("""
                INSERT INTO oauth_authorization_attempts(
                    state_hash, business_id, user_id, provider,
                    redirect_uri, encrypted_code_verifier, key_version,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)

    def consume_oauth_attempt(
        self, *, state_hash: str, business_id: str, user_id: str,
        provider: str, redirect_uri: str, now: str,
    ) -> dict[str, object]:
        with self.database.transaction() as db:
            row = db.execute("""
                SELECT state_hash, business_id, user_id, provider,
                       redirect_uri, encrypted_code_verifier, key_version,
                       created_at, expires_at, consumed_at
                FROM oauth_authorization_attempts
                WHERE state_hash = ?
                  AND business_id = ?
                  AND user_id = ?
                  AND provider = ?
                  AND redirect_uri = ?
            """, (
                state_hash, business_id, user_id, provider,
                redirect_uri,
            )).fetchone()

            if row is None:
                raise PermissionError("OAuth authorisation attempt is invalid.")

            if row["consumed_at"] is not None:
                raise PermissionError("OAuth authorisation attempt was already used.")

            if row["expires_at"] <= now:
                raise PermissionError("OAuth authorisation attempt has expired.")

            updated = db.execute("""
                UPDATE oauth_authorization_attempts
                SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at IS NULL
                  AND expires_at > ?
            """, (now, state_hash, now))

            if updated.rowcount != 1:
                raise PermissionError("OAuth authorisation attempt is no longer valid.")

            return dict(row)


'''

    if anchor not in repo:
        raise SystemExit("Repository insertion point not found.")

    repo = repo.replace(anchor, methods + anchor, 1)
    repo_path.write_text(repo)

# 3. OAuth service methods
service = service_path.read_text()

if "    def create_oauth_attempt(" not in service:
    service = service.replace(
        "import json\n",
        "import json\nimport base64\nimport hashlib\nimport secrets\nfrom datetime import datetime, timedelta, timezone\nfrom urllib.parse import urlsplit\n",
        1,
    )

    anchor = "    def connect(\n"

    methods = '''    @staticmethod
    def _validate_oauth_redirect_uri(redirect_uri: str) -> str:
        if not isinstance(redirect_uri, str) or not redirect_uri.strip():
            raise ValueError("A redirect URI is required.")

        value = redirect_uri.strip()
        if len(value) > 2048:
            raise ValueError("Redirect URI is too long.")

        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("Redirect URI must be a valid HTTPS URL.")

        return value

    def create_oauth_attempt(
        self, *, business_id: str, user_id: str, provider: str,
        redirect_uri: str, consent_confirmed: bool,
        ttl_seconds: int = 600,
    ) -> dict[str, str]:
        if consent_confirmed is not True:
            raise PermissionError("Explicit user consent is required.")

        if provider not in CONNECTOR_SCOPES:
            raise ValueError("Unsupported integration provider.")

        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 60 <= ttl_seconds <= 900
        ):
            raise ValueError("OAuth attempt lifetime must be 60 to 900 seconds.")

        business_id = business_id.strip() if isinstance(business_id, str) else ""
        user_id = user_id.strip() if isinstance(user_id, str) else ""
        if not business_id or not user_id:
            raise ValueError("Business and user identity are required.")

        redirect_uri = self._validate_oauth_redirect_uri(redirect_uri)

        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()

        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

        ciphertext = self.cipher.encrypt(verifier.encode("ascii"))
        key_version = getattr(self.cipher, "key_version", "custom")

        self.repository.create_oauth_attempt(
            state_hash=state_hash,
            business_id=business_id,
            user_id=user_id,
            provider=provider,
            redirect_uri=redirect_uri,
            encrypted_code_verifier=ciphertext,
            key_version=key_version,
            created_at=created_at,
            expires_at=expires_at,
        )

        return {
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "provider": provider,
            "redirect_uri": redirect_uri,
            "expires_at": expires_at,
        }

    def consume_oauth_attempt(
        self, *, state: str, business_id: str, user_id: str,
        provider: str, redirect_uri: str,
    ) -> dict[str, str]:
        if not isinstance(state, str) or not 32 <= len(state) <= 256:
            raise PermissionError("OAuth authorisation attempt is invalid.")

        redirect_uri = self._validate_oauth_redirect_uri(redirect_uri)
        state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()

        row = self.repository.consume_oauth_attempt(
            state_hash=state_hash,
            business_id=business_id,
            user_id=user_id,
            provider=provider,
            redirect_uri=redirect_uri,
            now=datetime.now(timezone.utc).isoformat(),
        )

        stored_version = str(row["key_version"])
        decrypt_for_version = getattr(self.cipher, "decrypt_for_version", None)

        if callable(decrypt_for_version):
            plaintext = decrypt_for_version(
                bytes(row["encrypted_code_verifier"]), stored_version
            )
        else:
            if stored_version != getattr(self.cipher, "key_version", "custom"):
                raise ValueError("OAuth verifier encryption key version mismatch.")
            plaintext = self.cipher.decrypt(bytes(row["encrypted_code_verifier"]))

        try:
            verifier = plaintext.decode("ascii")
        except (UnicodeDecodeError, AttributeError) as exc:
            raise ValueError("Stored PKCE verifier is invalid.") from exc

        if not 43 <= len(verifier) <= 128:
            raise ValueError("Stored PKCE verifier is invalid.")

        return {
            "code_verifier": verifier,
            "provider": str(row["provider"]),
            "redirect_uri": str(row["redirect_uri"]),
        }

'''

    if anchor not in service:
        raise SystemExit("Service insertion point not found.")

    service = service.replace(anchor, methods + anchor, 1)
    service_path.write_text(service)

# 4. Focused tests
tests = test_path.read_text()

if "test_oauth_attempt_is_single_use_and_returns_pkce_verifier" not in tests:
    additions = '''

def test_oauth_attempt_requires_explicit_consent(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(PermissionError):
        service.create_oauth_attempt(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
            consent_confirmed=False,
        )


def test_oauth_attempt_is_single_use_and_returns_pkce_verifier(integration_setup):
    database, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )

    assert attempt["code_challenge_method"] == "S256"
    assert len(attempt["code_challenge"]) == 43

    with database.connection() as db:
        stored = db.execute(
            "SELECT state_hash, encrypted_code_verifier "
            "FROM oauth_authorization_attempts"
        ).fetchone()

    assert stored is not None
    assert stored["state_hash"] != attempt["state"]
    assert attempt["state"] not in stored["state_hash"]
    assert stored["encrypted_code_verifier"] != attempt["state"].encode()

    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )

    assert len(result["code_verifier"]) >= 43
    assert result["provider"] == "gmail"

    with pytest.raises(PermissionError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )


def test_oauth_attempt_rejects_wrong_tenant_provider_and_redirect(integration_setup):
    _, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
    )

    invalid_contexts = (
        ("business-other", "user-a", "gmail", "https://example.com/oauth/callback"),
        ("business-a", "user-other", "gmail", "https://example.com/oauth/callback"),
        ("business-a", "user-a", "telegram", "https://example.com/oauth/callback"),
        ("business-a", "user-a", "gmail", "https://attacker.example/callback"),
    )

    for business_id, user_id, provider, redirect_uri in invalid_contexts:
        with pytest.raises(PermissionError):
            service.consume_oauth_attempt(
                state=attempt["state"],
                business_id=business_id,
                user_id=user_id,
                provider=provider,
                redirect_uri=redirect_uri,
            )

    # A failed context check must not consume the legitimate attempt.
    result = service.consume_oauth_attempt(
        state=attempt["state"],
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
    )
    assert result["provider"] == "gmail"


def test_oauth_attempt_rejects_expired_state(integration_setup):
    _, service, _ = integration_setup

    attempt = service.create_oauth_attempt(
        business_id="business-a",
        user_id="user-a",
        provider="gmail",
        redirect_uri="https://example.com/oauth/callback",
        consent_confirmed=True,
        ttl_seconds=60,
    )

    # Move the stored expiry into the past to test expiry deterministically.
    with service.repository.database.transaction() as db:
        db.execute(
            "UPDATE oauth_authorization_attempts "
            "SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE state_hash = ?",
            (__import__("hashlib").sha256(
                attempt["state"].encode("utf-8")
            ).hexdigest(),),
        )

    with pytest.raises(PermissionError):
        service.consume_oauth_attempt(
            state=attempt["state"],
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="https://example.com/oauth/callback",
        )


def test_oauth_attempt_rejects_insecure_redirect_uri(integration_setup):
    _, service, _ = integration_setup

    with pytest.raises(ValueError):
        service.create_oauth_attempt(
            business_id="business-a",
            user_id="user-a",
            provider="gmail",
            redirect_uri="http://example.com/callback",
            consent_confirmed=True,
        )
'''
    tests += additions
    test_path.write_text(tests)

print("OAuth foundation and migration 26 applied. Backups preserved.")
