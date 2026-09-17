from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass


CREDENTIAL_FORMAT_VERSION = 1


@dataclass(frozen=True)
class ScryptPolicy:
    """
    Explicit password-hashing policy.

    Production values are deliberately explicit rather than relying on
    hashlib defaults. The encoded credential stores the policy parameters,
    allowing future upgrades without invalidating old credentials.
    """

    n: int = 2**17
    r: int = 8
    p: int = 1
    dklen: int = 32
    maxmem: int = 256 * 1024 * 1024
    salt_bytes: int = 16

    def __post_init__(self) -> None:
        if self.n <= 1 or self.n & (self.n - 1):
            raise ValueError("scrypt n must be a power of two greater than one.")
        if self.r <= 0 or self.p <= 0 or self.dklen <= 0:
            raise ValueError("scrypt cost parameters must be positive.")
        if self.maxmem <= 0 or self.salt_bytes < 16:
            raise ValueError("Invalid scrypt memory or salt policy.")


PRODUCTION_SCRYPT_POLICY = ScryptPolicy()

# Encoded credential parameters are attacker-controlled once a credential
# record has been tampered with. Keep verification bounded independently of
# the policy encoded in the credential so a forged record cannot request
# unbounded CPU/memory work.
MAX_DECODED_SCRYPT_N = 2**18
MAX_DECODED_SCRYPT_R = 8
MAX_DECODED_SCRYPT_P = 4
MAX_DECODED_SCRYPT_DKLEN = 64
MAX_DECODED_SCRYPT_MAXMEM = 256 * 1024 * 1024
MAX_DECODED_SCRYPT_SALT_BYTES = 64
MAX_DECODED_SCRYPT_DIGEST_BYTES = 64


class ScryptPasswordHasher:
    """Versioned password hashing and constant-time verification."""

    def __init__(self, policy: ScryptPolicy = PRODUCTION_SCRYPT_POLICY) -> None:
        if not isinstance(policy, ScryptPolicy):
            raise TypeError("policy must be a ScryptPolicy.")
        self._policy = policy

    @property
    def policy(self) -> ScryptPolicy:
        return self._policy

    def hash(self, password: str) -> str:
        _validate_password(password)

        salt = secrets.token_bytes(self._policy.salt_bytes)

        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=self._policy.n,
            r=self._policy.r,
            p=self._policy.p,
            dklen=self._policy.dklen,
            maxmem=self._policy.maxmem,
        )

        return _encode(
            self._policy,
            salt,
            derived,
        )

    def verify(self, password: str, encoded: str) -> bool:
        if not isinstance(password, str) or not isinstance(encoded, str):
            return False

        try:
            _validate_password(password)
            policy, salt, expected = _decode(encoded)
            actual = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=policy.n,
                r=policy.r,
                p=policy.p,
                dklen=policy.dklen,
                maxmem=policy.maxmem,
            )
        except (ValueError, TypeError, UnicodeError, OverflowError):
            return False

        return hmac.compare_digest(actual, expected)


def _validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise TypeError("password must be a string.")
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters.")
    if len(password) > 1024:
        raise ValueError("password exceeds the maximum allowed length.")


def _encode(policy: ScryptPolicy, salt: bytes, derived: bytes) -> str:
    fields = (
        str(CREDENTIAL_FORMAT_VERSION),
        str(policy.n),
        str(policy.r),
        str(policy.p),
        str(policy.dklen),
        str(policy.maxmem),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )
    return "$".join(fields)


def _decode(encoded: str) -> tuple[ScryptPolicy, bytes, bytes]:
    parts = encoded.split("$")
    if len(parts) != 8:
        raise ValueError("Invalid credential format.")

    (
        version,
        n,
        r,
        p,
        dklen,
        maxmem,
        salt_text,
        digest_text,
    ) = parts

    if int(version) != CREDENTIAL_FORMAT_VERSION:
        raise ValueError("Unsupported credential format.")

    try:
        parsed_version = int(version)
        parsed_n = int(n)
        parsed_r = int(r)
        parsed_p = int(p)
        parsed_dklen = int(dklen)
        parsed_maxmem = int(maxmem)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid credential parameters.") from exc

    if parsed_version != CREDENTIAL_FORMAT_VERSION:
        raise ValueError("Unsupported credential format.")

    if (
        parsed_n <= 1
        or parsed_n > MAX_DECODED_SCRYPT_N
        or parsed_n & (parsed_n - 1)
        or parsed_r <= 0
        or parsed_r > MAX_DECODED_SCRYPT_R
        or parsed_p <= 0
        or parsed_p > MAX_DECODED_SCRYPT_P
        or parsed_dklen <= 0
        or parsed_dklen > MAX_DECODED_SCRYPT_DKLEN
        or parsed_maxmem <= 0
        or parsed_maxmem > MAX_DECODED_SCRYPT_MAXMEM
    ):
        raise ValueError("Credential parameters exceed verification limits.")

    try:
        salt = base64.b64decode(
            salt_text.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        digest = base64.b64decode(
            digest_text.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid credential encoding.") from exc

    if not (16 <= len(salt) <= MAX_DECODED_SCRYPT_SALT_BYTES):
        raise ValueError("Invalid credential salt length.")

    if not (1 <= len(digest) <= MAX_DECODED_SCRYPT_DIGEST_BYTES):
        raise ValueError("Invalid credential digest length.")

    policy = ScryptPolicy(
        n=parsed_n,
        r=parsed_r,
        p=parsed_p,
        dklen=parsed_dklen,
        maxmem=parsed_maxmem,
        salt_bytes=len(salt),
    )

    if len(digest) != policy.dklen:
        raise ValueError("Invalid credential digest length.")

    return policy, salt, digest
