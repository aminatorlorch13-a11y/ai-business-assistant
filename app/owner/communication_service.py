from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol
from uuid import uuid4
import json
import re
import hmac
import secrets
from datetime import timedelta

from app.whatsapp.provider import WhatsAppProviderError, WhatsAppProviderOutcomeUnknown

from app.persistence.communication_repository import (
    CHANNELS,
    SQLiteCommunicationRepository,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required(value: str, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters.")
    return value.strip()


class EndpointVerifier(Protocol):
    def verify_endpoint(
        self, *, channel: str, endpoint: str, proof: str
    ) -> bool: ...


class IdentityProvisioningVerifier(Protocol):
    def verify_assignment(
        self, *, business_id: str, provider: str,
        assigned_identity: str, provider_reference: str,
    ) -> bool: ...






@dataclass(frozen=True)
class CommunicationEndpoint:
    endpoint_id: str
    channel: str
    endpoint: str


class OwnerCommunicationService:
    """Tenant-scoped communication authorisation and encrypted endpoint service."""

    def __init__(
        self, *, repository: SQLiteCommunicationRepository,
        cipher, lifestyle_service,
        endpoint_verifier: EndpointVerifier | None = None,
        identity_verifier: IdentityProvisioningVerifier | None = None,
        whatsapp_provider=None,
        sender_hash_secret: str | None = None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.lifestyle_service = lifestyle_service
        self.endpoint_verifier = endpoint_verifier
        self.identity_verifier = identity_verifier
        self.whatsapp_provider = whatsapp_provider
        self.sender_hash_secret = sender_hash_secret

    def _owner(self, principal, business_id: str):
        business_id = _required(business_id, "business_id")
        self.lifestyle_service.identity(principal, business_id)
        return business_id

    def _encrypt(self, value: str) -> tuple[bytes, str]:
        encrypted = self.cipher.encrypt(value.encode("utf-8"))
        key_version = getattr(self.cipher, "key_version", None)
        if not isinstance(encrypted, bytes) or not encrypted:
            raise RuntimeError("Endpoint encryption failed.")
        if not isinstance(key_version, str) or not key_version:
            raise RuntimeError("Encryption key version is unavailable.")
        return encrypted, key_version

    def _decrypt(self, encrypted: bytes, key_version: str) -> str:
        versioned = getattr(self.cipher, "decrypt_for_version", None)
        plaintext = (
            versioned(encrypted, key_version)
            if callable(versioned)
            else self.cipher.decrypt(encrypted)
        )
        return plaintext.decode("utf-8")

    def register_endpoint(
        self, principal, business_id: str, *,
        channel: str, endpoint: str, verification_proof: str,
        consent_granted: bool,
    ) -> str:
        business_id = self._owner(principal, business_id)
        user_id = _required(principal.user_id, "user_id")
        if channel not in CHANNELS:
            raise ValueError("Unsupported communication channel.")
        endpoint = _required(endpoint, "endpoint")
        proof = _required(verification_proof, "verification_proof")
        if consent_granted is not True:
            raise PermissionError("Explicit owner consent is required.")

        if channel == "whatsapp":
            raise PermissionError("WhatsApp endpoints must be verified through the Meta OTP challenge.")
        if self.endpoint_verifier is None:
            raise RuntimeError("A trusted endpoint verifier is not configured.")
        if not self.endpoint_verifier.verify_endpoint(
            channel=channel, endpoint=endpoint, proof=proof
        ):
            raise PermissionError("Endpoint verification failed.")

        encrypted, key_version = self._encrypt(endpoint)
        fingerprint = sha256(
            f"{channel}:{endpoint.strip().casefold()}".encode("utf-8")
        ).hexdigest()
        endpoint_id = str(uuid4())
        timestamp = _now()

        self.repository.register_endpoint(
            endpoint_id=endpoint_id,
            business_id=business_id,
            user_id=user_id,
            channel=channel,
            encrypted_endpoint=encrypted,
            key_version=key_version,
            fingerprint=fingerprint,
            verified_at=timestamp,
            consent_granted_at=timestamp,
        )
        return endpoint_id



    def _whatsapp_verification_keys(self) -> tuple[bytes, bytes]:
        secret = self.sender_hash_secret
        if not isinstance(secret, str) or len(secret) < 32:
            raise RuntimeError("A strong WhatsApp sender hash secret is not configured.")
        master = secret.encode("utf-8")
        fingerprint_key = hmac.new(
            master, b"amination:whatsapp:endpoint-fingerprint:v1", sha256
        ).digest()
        proof_key = hmac.new(
            master, b"amination:whatsapp:endpoint-otp:v1", sha256
        ).digest()
        return fingerprint_key, proof_key

    @staticmethod
    def _whatsapp_number(value: str) -> tuple[str, str]:
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ValueError("A valid WhatsApp phone number is required.")
        digits = re.sub(r"\D", "", value)
        if not 8 <= len(digits) <= 15 or digits.startswith("0"):
            raise ValueError("Use the phone number in international format, including its country code.")
        return digits, "+" + digits

    def begin_whatsapp_endpoint_verification(
        self, principal, business_id: str, *, endpoint: str,
        consent_granted: bool,
    ) -> dict[str, object]:
        business_id = self._owner(principal, business_id)
        if consent_granted is not True:
            raise PermissionError("Explicit consent is required.")
        if self.whatsapp_provider is None:
            raise RuntimeError("The real Meta WhatsApp provider is not configured.")

        digits, normalized_endpoint = self._whatsapp_number(endpoint)
        identity_record = self.get_tenant_identity(principal, business_id)
        if not isinstance(identity_record, dict):
            raise RuntimeError("The tenant's Meta WhatsApp identity could not be verified.")

        provider = identity_record.get("provider")
        status = identity_record.get("status")
        provider_account_id = identity_record.get("identity")
        if provider != "meta" or status != "active":
            raise PermissionError("An active, independently verified Meta WhatsApp identity is required.")
        if not isinstance(provider_account_id, str) or not re.fullmatch(r"\d{5,32}", provider_account_id):
            raise RuntimeError("The active Meta phone number identity is invalid.")

        fingerprint_key, proof_key = self._whatsapp_verification_keys()
        fingerprint = hmac.new(
            fingerprint_key, f"whatsapp:{digits}".encode(), sha256
        ).hexdigest()
        challenge_id = str(uuid4())
        otp = f"{secrets.randbelow(1_000_000):06d}"
        proof_digest = hmac.new(
            proof_key, f"{challenge_id}:{otp}".encode(), sha256
        ).hexdigest()
        encrypted_endpoint, key_version = self._encrypt(normalized_endpoint)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat()

        self.repository.create_endpoint_challenge(
            challenge_id=challenge_id,
            business_id=business_id,
            user_id=_required(str(getattr(principal, "user_id", "")), "user_id"),
            channel="whatsapp",
            encrypted_endpoint=encrypted_endpoint,
            provider_account_id=provider_account_id,
            consent_granted=True,
            key_version=key_version,
            fingerprint=fingerprint,
            proof_digest=proof_digest,
            expires_at=expires_at,
            max_attempts=5,
        )

        message = (
            f"Your Amination verification code is {otp}. "
            f"Reply: VERIFY {otp}. Expires in 10 minutes. Do not share this code."
        )
        try:
            message_id = self.whatsapp_provider.send_text(
                provider_account_id, normalized_endpoint, message
            )
            if not isinstance(message_id, str) or not message_id.strip():
                raise RuntimeError("Meta did not confirm message acceptance.")
        except WhatsAppProviderOutcomeUnknown:
            return {"status": "delivery_status_unknown", "expires_in_seconds": 600}
        except WhatsAppProviderError as exc:
            self.repository.cancel_endpoint_challenge(challenge_id=challenge_id)
            raise RuntimeError("WhatsApp verification delivery failed.") from exc
        except RuntimeError:
            self.repository.cancel_endpoint_challenge(challenge_id=challenge_id)
            raise

        return {"status": "verification_sent", "expires_in_seconds": 600}

    def handle_whatsapp_verification_message(
        self, *, provider_account_id: str, sender_id: str,
        provider_message_id: str, text: str,
    ) -> bool:
        match = (
            re.fullmatch(r"VERIFY\s+(\d{6})", text.strip(), re.IGNORECASE)
            if isinstance(text, str) else None
        )
        if match is None:
            return False

        if not self.repository.claim_endpoint_verification_message(
            provider_account_id=provider_account_id,
            provider_message_id=provider_message_id,
        ):
            return True

        digits, _ = self._whatsapp_number(sender_id)
        fingerprint_key, proof_key = self._whatsapp_verification_keys()
        fingerprint = hmac.new(
            fingerprint_key, f"whatsapp:{digits}".encode(), sha256
        ).hexdigest()

        challenge_id = self.repository.find_pending_endpoint_challenge(
            channel="whatsapp",
            fingerprint=fingerprint,
            provider_account_id=provider_account_id,
        )
        if challenge_id is None:
            return True

        proof_digest = hmac.new(
            proof_key, f"{challenge_id}:{match.group(1)}".encode(), sha256
        ).hexdigest()

        self.repository.confirm_endpoint_challenge(
            challenge_id=challenge_id,
            proof_digest=proof_digest,
            endpoint_id=str(uuid4()),
            provider_account_id=provider_account_id,
            fingerprint=fingerprint,
        )
        return True
    def list_endpoints(self, principal, business_id: str) -> list[CommunicationEndpoint]:
        business_id = self._owner(principal, business_id)
        user_id = _required(principal.user_id, "user_id")
        result = []
        for row in self.repository.list_enabled_endpoints(
            business_id=business_id, user_id=user_id
        ):
            endpoint = self._decrypt(
                row["encrypted_endpoint"], row["key_version"]
            )
            result.append(CommunicationEndpoint(
                endpoint_id=row["endpoint_id"],
                channel=row["channel"],
                endpoint=endpoint,
            ))
        return result

    def revoke_endpoint(
        self, principal, business_id: str, endpoint_id: str
    ) -> bool:
        business_id = self._owner(principal, business_id)
        return self.repository.revoke_endpoint(
            endpoint_id=_required(endpoint_id, "endpoint_id"),
            business_id=business_id,
            user_id=_required(principal.user_id, "user_id"),
        )

    def queue_event_delivery(
        self, principal, business_id: str, *,
        event_id: str, max_attempts: int = 3,
        next_attempt_at: str | None = None,
    ) -> int:
        business_id = self._owner(principal, business_id)
        user_id = _required(principal.user_id, "user_id")
        preferences = self.lifestyle_service.get_preferences(
            principal, business_id
        )
        preferred = (
            preferences.get("preferred_channels")
            if isinstance(preferences, dict)
            else getattr(preferences, "preferred_channels", None)
        )
        if not isinstance(preferred, (list, tuple)) or not preferred:
            return 0
        if any(channel not in CHANNELS for channel in preferred):
            raise ValueError("Owner channel preferences contain an unsupported channel.")

        endpoints = self.repository.list_enabled_endpoints(
            business_id=business_id, user_id=user_id
        )
        endpoint_ids = [
            row["endpoint_id"] for row in endpoints
            if row["channel"] in set(preferred)
        ]
        return self.repository.queue_delivery(
            event_id=_required(event_id, "event_id"),
            business_id=business_id,
            user_id=user_id,
            endpoint_ids=endpoint_ids,
            max_attempts=max_attempts,
            next_attempt_at=next_attempt_at,
        )

    def activate_tenant_identity(
        self, principal, business_id: str, *,
        provider: str, assigned_identity: str,
        provider_reference: str,
    ) -> None:
        business_id = self._owner(principal, business_id)
        provider = _required(provider, "provider")
        assigned_identity = _required(assigned_identity, "assigned_identity")
        provider_reference = _required(provider_reference, "provider_reference")

        if self.identity_verifier is None:
            raise RuntimeError("A trusted tenant identity verifier is not configured.")
        if not self.identity_verifier.verify_assignment(
            business_id=business_id,
            provider=provider,
            assigned_identity=assigned_identity,
            provider_reference=provider_reference,
        ):
            raise PermissionError(
                "The provider assignment could not be independently verified."
            )

        encrypted, key_version = self._encrypt(assigned_identity)
        self.repository.save_tenant_identity(
            business_id=business_id,
            provider=provider,
            encrypted_identity=encrypted,
            key_version=key_version,
            status="active",
            provisioned_at=_now(),
        )

    def get_tenant_identity(self, principal, business_id: str) -> dict | None:
        business_id = self._owner(principal, business_id)
        row = self.repository.get_tenant_identity(business_id=business_id)
        if row is None:
            return None
        return {
            "provider": row["provider"],
            "identity": self._decrypt(
                row["encrypted_identity"], row["key_version"]
            ) if row["status"] == "active" else None,
            "status": row["status"],
            "provisioned_at": row["provisioned_at"],
        }
