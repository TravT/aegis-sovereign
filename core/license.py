#!/usr/bin/env python3
"""
Offline Ed25519 Cryptographic Licensing Engine.
Aegis Sovereign Knowledge Appliance.

Enforces air-gapped cryptographic validation of software licenses without cloud egress.
Zero external telemetry, verifiable offline via Ed25519 asymmetric cryptography.
"""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


class LicenseError(Exception):
    """Base exception for all licensing errors."""
    pass


class LicenseExpiredError(LicenseError):
    """Raised when an offline license has passed its expiration timestamp."""
    pass


class InvalidLicenseSignatureError(LicenseError):
    """Raised when cryptographic signature verification fails or token is malformed."""
    pass


class LicenseTamperedError(InvalidLicenseSignatureError):
    """Raised specifically when payload or signature tampering is detected."""
    pass


class LicenseNotFoundError(LicenseError):
    """Raised when the specified license file does not exist."""
    pass


@dataclass
class LicenseData:
    """
    Decrypted and validated offline license payload.

    Fields:
    - license_id: Unique UUID or serial for this license.
    - customer_id: Customer or organization identifier.
    - plan_tier: Plan tier string ('free', 'pro', 'enterprise').
    - issued_at: ISO8601 string or datetime of issuance.
    - expires_at: ISO8601 string or datetime of expiration (None for perpetual).
    - max_seats: Number of authorized concurrent seats.
    - max_documents: Document volume cap (None for unlimited).
    - features: Feature toggles dict (multimodal_clip, raptor_synthesis, gpu_delegation, custom_ontology).
    """
    license_id: str
    customer_id: str
    plan_tier: str
    issued_at: Union[str, datetime.datetime]
    expires_at: Optional[Union[str, datetime.datetime]] = None
    max_seats: int = 1
    max_documents: Optional[int] = None
    features: Dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        # Normalize plan tier string
        if hasattr(self.plan_tier, "value"):
            self.plan_tier = str(self.plan_tier.value).lower()
        else:
            self.plan_tier = str(self.plan_tier).lower()

        # Normalize timestamps to ISO format strings if datetime
        if isinstance(self.issued_at, datetime.datetime):
            self.issued_at = self.issued_at.isoformat()
        if isinstance(self.expires_at, datetime.datetime):
            self.expires_at = self.expires_at.isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Returns canonical serializable dictionary representation."""
        return {
            "license_id": str(self.license_id),
            "customer_id": str(self.customer_id),
            "plan_tier": str(self.plan_tier),
            "issued_at": str(self.issued_at),
            "expires_at": str(self.expires_at) if self.expires_at is not None else None,
            "max_seats": int(self.max_seats),
            "max_documents": int(self.max_documents) if self.max_documents is not None else None,
            "features": {str(k): bool(v) for k, v in self.features.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LicenseData":
        """Instantiates LicenseData from a dictionary."""
        return cls(
            license_id=str(data["license_id"]),
            customer_id=str(data["customer_id"]),
            plan_tier=str(data["plan_tier"]),
            issued_at=str(data["issued_at"]),
            expires_at=str(data["expires_at"]) if data.get("expires_at") is not None else None,
            max_seats=int(data.get("max_seats", 1)),
            max_documents=int(data["max_documents"]) if data.get("max_documents") is not None else None,
            features=dict(data.get("features", {})),
        )

    def is_expired(self, current_time: Optional[datetime.datetime] = None) -> bool:
        """Checks if the license has expired relative to current_time (UTC)."""
        if self.expires_at is None:
            return False

        now = current_time or datetime.datetime.now(datetime.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        exp = self.expires_at
        if isinstance(exp, str):
            exp = datetime.datetime.fromisoformat(exp)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=datetime.timezone.utc)

        return now > exp


class SovereignLicenseManager:
    """
    Offline Ed25519 Cryptographic License Manager.

    Provides keypair generation, deterministic canonical serialization,
    asymmetric signature generation, and verification under 1ms.
    """

    @staticmethod
    def generate_keypair() -> Tuple[bytes, bytes]:
        """
        Generates a new Ed25519 private/public keypair in PEM format.

        Returns:
            Tuple[bytes, bytes]: (private_key_pem, public_key_pem)
        """
        private_key = ed25519.Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return private_pem, public_pem

    @staticmethod
    def sign_license(data: LicenseData, private_key_pem: bytes) -> str:
        """
        Signs a LicenseData payload using an Ed25519 private key.

        Returns:
            str: Base64-encoded signed license token.
        """
        try:
            private_key = serialization.load_pem_private_key(private_key_pem, password=None)
            if not isinstance(private_key, ed25519.Ed25519PrivateKey):
                raise ValueError("Supplied key is not an Ed25519 private key")
        except Exception as exc:
            raise InvalidLicenseSignatureError(f"Failed to load Ed25519 private key: {exc}") from exc

        payload_dict = data.to_dict()
        # Canonical JSON serialization: sorted keys, compact separators
        canonical_json = json.dumps(payload_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
        signature = private_key.sign(canonical_json)

        envelope = {
            "version": 1,
            "algorithm": "Ed25519",
            "payload": payload_dict,
            "signature": base64.b64encode(signature).decode('utf-8'),
        }

        envelope_bytes = json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return base64.b64encode(envelope_bytes).decode('utf-8')

    @staticmethod
    def verify_license(
        token: str,
        public_key_pem: bytes,
        check_expiry: bool = True,
        current_time: Optional[datetime.datetime] = None,
    ) -> LicenseData:
        """
        Verifies the cryptographic Ed25519 signature and validity of a license token.

        Args:
            token: Base64-encoded license string.
            public_key_pem: Ed25519 public key in PEM format.
            check_expiry: If True, asserts the license has not expired.
            current_time: Optional datetime override for expiry testing.

        Returns:
            LicenseData: Verified license data.

        Raises:
            InvalidLicenseSignatureError / LicenseTamperedError: Signature or envelope invalid.
            LicenseExpiredError: Expiration date is in the past.
        """
        if not token or not isinstance(token, str):
            raise InvalidLicenseSignatureError("Empty or invalid license token")

        try:
            envelope_bytes = base64.b64decode(token.strip().encode('utf-8'))
            envelope = json.loads(envelope_bytes.decode('utf-8'))
            if not isinstance(envelope, dict):
                raise ValueError("Envelope must be a JSON object")
            payload_dict = envelope["payload"]
            signature = base64.b64decode(envelope["signature"].encode('utf-8'))
        except Exception as exc:
            raise InvalidLicenseSignatureError(f"Malformed license token envelope: {exc}") from exc

        try:
            public_key = serialization.load_pem_public_key(public_key_pem)
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                raise ValueError("Supplied key is not an Ed25519 public key")
        except Exception as exc:
            raise InvalidLicenseSignatureError(f"Failed to load Ed25519 public key: {exc}") from exc

        # Reconstruct canonical JSON for signature verification
        canonical_json = json.dumps(payload_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')

        try:
            public_key.verify(signature, canonical_json)
        except InvalidSignature as exc:
            raise LicenseTamperedError("Cryptographic signature mismatch (tampering detected)") from exc
        except Exception as exc:
            raise InvalidLicenseSignatureError(f"Verification error: {exc}") from exc

        license_data = LicenseData.from_dict(payload_dict)

        if check_expiry and license_data.is_expired(current_time=current_time):
            raise LicenseExpiredError(
                f"License '{license_data.license_id}' for customer '{license_data.customer_id}' "
                f"expired on {license_data.expires_at}."
            )

        return license_data

    @staticmethod
    def save_license_file(token: str, path: Union[str, Path]) -> None:
        """Saves a license token string to disk."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(token.strip() + "\n", encoding="utf-8")

    @staticmethod
    def load_license_file(
        path: Union[str, Path],
        public_key_pem: bytes,
        check_expiry: bool = True,
        current_time: Optional[datetime.datetime] = None,
    ) -> LicenseData:
        """
        Loads and cryptographically verifies a license file from disk.

        Args:
            path: Path to `.aegis` license file.
            public_key_pem: Ed25519 public key PEM.
            check_expiry: If True, checks expiration date.
            current_time: Optional datetime override.

        Returns:
            LicenseData: Verified license data.
        """
        target_path = Path(path)
        if not target_path.is_file():
            raise LicenseNotFoundError(f"License file does not exist: {target_path}")

        token = target_path.read_text(encoding="utf-8").strip()
        return SovereignLicenseManager.verify_license(
            token,
            public_key_pem,
            check_expiry=check_expiry,
            current_time=current_time,
        )
