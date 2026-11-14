from __future__ import annotations

import json
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from collections.abc import Mapping

from app.integrations.models import CONNECTOR_SCOPES
from app.integrations.security import SecretCipher
from app.persistence.integration_repository import SQLiteIntegrationRepository


class IntegrationService:
    def __init__(
        self, repository: SQLiteIntegrationRepository, cipher: SecretCipher,
    ) -> None:
        self.repository = repository
        self.cipher = cipher

    @staticmethod
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

    def connect(
        self, *, business_id: str, user_id: str, provider: str,
        external_account_id: str, scopes: set[str],
        secret_payload: Mapping[str, str], consent_confirmed: bool,
    ) -> str:
        if consent_confirmed is not True:
            raise PermissionError("Explicit user consent is required.")
        allowed = CONNECTOR_SCOPES.get(provider)
        if allowed is None:
            raise ValueError("Unsupported integration provider.")
        if not scopes or not scopes.issubset(allowed):
            raise ValueError("Requested scopes are empty or not supported.")
        if not isinstance(secret_payload, Mapping) or not secret_payload:
            raise ValueError("A non-empty secret payload is required.")
        if any(
            not isinstance(k, str) or not k.strip()
            or not isinstance(v, str) or not v
            for k, v in secret_payload.items()
        ):
            raise ValueError("Secret payload must contain non-empty string keys and values.")

        connection_id = str(uuid4())
        ciphertext = self.cipher.encrypt(
            json.dumps(dict(secret_payload), separators=(",", ":")).encode("utf-8")
        )
        self.repository.create_connection_with_secret(
            connection_id=connection_id, business_id=business_id,
            user_id=user_id, provider=provider,
            external_account_id=external_account_id, scopes=set(scopes),
            ciphertext=ciphertext,
            key_version=getattr(self.cipher, "key_version", "custom"),
        )
        return connection_id

    def list_active_connections(
        self, *, provider: str, business_id: str, user_id: str, scope: str,
    ):
        """Return active connections with the requested active permission."""
        return self.repository.list_active_connections(
            provider=provider,
            business_id=business_id,
            user_id=user_id,
            scope=scope,
        )

    def has_permission(
        self, *, connection_id: str, business_id: str,
        user_id: str, scope: str,
    ) -> bool:
        return self.repository.has_permission(
            connection_id=connection_id, business_id=business_id,
            user_id=user_id, scope=scope,
        )

    def read_secret_payload(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> dict[str, str]:
        ciphertext, stored_version = self.repository.get_encrypted_secret(
            connection_id=connection_id, business_id=business_id, user_id=user_id,
        )
        decrypt_for_version = getattr(self.cipher, "decrypt_for_version", None)
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
        if not isinstance(payload, dict):
            raise RuntimeError("Stored integration secret has an invalid format.")
        return payload

    def replace_secret_payload(
        self, *, connection_id: str, business_id: str, user_id: str,
        expected_payload: Mapping[str, str],
        replacement_payload: Mapping[str, str],
    ) -> None:
        """Replace an OAuth payload only if the encrypted source is unchanged."""
        if not isinstance(expected_payload, Mapping) or not expected_payload:
            raise ValueError("Expected secret payload is required.")
        if not isinstance(replacement_payload, Mapping) or not replacement_payload:
            raise ValueError("Replacement secret payload is required.")

        for payload in (expected_payload, replacement_payload):
            if any(
                not isinstance(key, str) or not key.strip()
                or not isinstance(value, str) or not value
                for key, value in payload.items()
            ):
                raise ValueError("Secret payload must contain non-empty strings.")

        ciphertext, stored_version = self.repository.get_encrypted_secret(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
        )

        decrypt_for_version = getattr(self.cipher, "decrypt_for_version", None)
        if callable(decrypt_for_version):
            plaintext = decrypt_for_version(ciphertext, stored_version)
        else:
            expected_version = getattr(self.cipher, "key_version", None)
            if expected_version is not None and stored_version != expected_version:
                raise RuntimeError(
                    "Stored integration secret uses an unsupported key version."
                )
            plaintext = self.cipher.decrypt(ciphertext)

        try:
            current_payload = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Stored integration secret is invalid.") from exc

        if current_payload != dict(expected_payload):
            raise RuntimeError(
                "Gmail credentials changed during refresh; reload before retrying."
            )

        replacement_ciphertext = self.cipher.encrypt(
            json.dumps(
                dict(replacement_payload), separators=(",", ":")
            ).encode("utf-8")
        )
        self.repository.replace_oauth_secret(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            expected_ciphertext=ciphertext,
            expected_key_version=stored_version,
            ciphertext=replacement_ciphertext,
            key_version=getattr(self.cipher, "key_version", "custom"),
        )

    def revoke_permission(
        self, *, connection_id: str, business_id: str, user_id: str,
        scope: str,
    ) -> None:
        self.repository.revoke_permission(
            connection_id=connection_id,
            business_id=business_id,
            user_id=user_id,
            scope=scope,
        )

    def revoke(
        self, *, connection_id: str, business_id: str, user_id: str,
    ) -> None:
        self.repository.revoke_connection(
            connection_id=connection_id, business_id=business_id, user_id=user_id,
        )


    def rotate_secret(
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

