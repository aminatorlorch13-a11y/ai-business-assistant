from __future__ import annotations

import os
from typing import Protocol
from collections.abc import Mapping


class SecretCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class FernetSecretCipher:
    """Authenticated encryption for integration secrets. Never falls back to plaintext."""

    key_version = "fernet-v1"

    def __init__(self, key: str | bytes) -> None:
        try:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as exc:
            raise ValueError("A valid Fernet encryption key is required.") from exc

    @classmethod
    def from_environment(cls) -> "FernetSecretCipher":
        key = os.environ.get("AMINATION_INTEGRATION_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "AMINATION_INTEGRATION_ENCRYPTION_KEY is not configured."
            )
        return cls(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, bytes) or not plaintext:
            raise ValueError("Secret payload must be non-empty bytes.")
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise ValueError("Encrypted payload must be non-empty bytes.")
        try:
            return self._fernet.decrypt(ciphertext)
        except Exception as exc:
            raise RuntimeError("Integration secret could not be authenticated.") from exc


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
