"""ADR-08: `.sovereign-capsule` Cryptographic Portability Engine.

Implements Zstandard compression + AES-256-GCM authenticated encryption with
PBKDF2-HMAC-SHA256 (200,000 iterations) key derivation for zero-trust knowledge
vault portability.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Union

import zstandard as zstd
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class CapsuleIntegrityError(Exception):
    """Raised when a .sovereign-capsule fails cryptographic authentication or integrity verification."""


class SovereignCapsuleManager:
    """Manages export and import of AES-256-GCM + Zstandard `.sovereign-capsule` archives."""

    MAGIC: bytes = b"AEGISCAP\x01"
    SALT_BYTES: int = 16
    NONCE_BYTES: int = 12
    DIGEST_BYTES: int = 32
    HEADER_BYTES: int = len(MAGIC) + SALT_BYTES + NONCE_BYTES + DIGEST_BYTES  # 69 bytes
    DEFAULT_KDF_ITERATIONS: int = 200_000
    DEFAULT_ZSTD_LEVEL: int = 10

    def __init__(
        self,
        kdf_iterations: int = DEFAULT_KDF_ITERATIONS,
        compression_level: int = DEFAULT_ZSTD_LEVEL,
    ) -> None:
        self.kdf_iterations = int(kdf_iterations)
        self.compression_level = int(compression_level)

    def _derive_key(self, passphrase: Union[str, bytes], salt: bytes) -> bytes:
        """Derive a 256-bit key using PBKDF2-HMAC-SHA256 (or accept raw 32-byte key)."""
        if not passphrase:
            raise ValueError("Passphrase or key material must not be empty")

        if isinstance(passphrase, bytes) and len(passphrase) == 32:
            return passphrase

        passphrase_bytes = (
            passphrase.encode("utf-8") if isinstance(passphrase, str) else bytes(passphrase)
        )
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.kdf_iterations,
        )
        return kdf.derive(passphrase_bytes)

    def export_capsule(
        self,
        payload_dict: Dict[str, Any],
        output_path: Union[str, Path],
        passphrase: Union[str, bytes],
    ) -> Dict[str, Any]:
        """Compress payload with Zstandard and encrypt with AES-256-GCM into a .sovereign-capsule file."""
        if not isinstance(payload_dict, dict):
            raise TypeError("payload_dict must be a dictionary")

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        serialized_bytes = json.dumps(
            payload_dict,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        manifest_digest = hashlib.sha256(serialized_bytes).digest()
        manifest_sha256_hex = manifest_digest.hex()

        compressor = zstd.ZstdCompressor(level=self.compression_level)
        compressed_bytes = compressor.compress(serialized_bytes)

        salt = os.urandom(self.SALT_BYTES)
        nonce = os.urandom(self.NONCE_BYTES)
        key = self._derive_key(passphrase=passphrase, salt=salt)

        header = self.MAGIC + salt + nonce + manifest_digest
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, compressed_bytes, header)

        capsule_blob = header + ciphertext
        out_path.write_bytes(capsule_blob)

        uncompressed_len = len(serialized_bytes)
        compressed_len = len(compressed_bytes)
        ratio = float(uncompressed_len) / float(max(1, compressed_len))

        return {
            "capsule_path": str(out_path),
            "magic": self.MAGIC.decode("latin1"),
            "uncompressed_bytes": uncompressed_len,
            "compressed_bytes": compressed_len,
            "capsule_bytes": len(capsule_blob),
            "compression_ratio": round(ratio, 3),
            "manifest_sha256": manifest_sha256_hex,
            "algorithm": "AES-256-GCM+ZSTD",
            "kdf": "PBKDF2-HMAC-SHA256",
            "iterations": self.kdf_iterations,
        }

    def import_capsule(
        self,
        capsule_path: Union[str, Path],
        passphrase: Union[str, bytes],
    ) -> Dict[str, Any]:
        """Verify AES-256-GCM tag, decompress Zstandard stream, and restore payload dictionary."""
        in_path = Path(capsule_path)
        if not in_path.exists():
            raise FileNotFoundError(f"Capsule file not found: {in_path}")

        capsule_blob = in_path.read_bytes()
        if len(capsule_blob) <= self.HEADER_BYTES + 16:  # 16-byte GCM tag minimum
            raise CapsuleIntegrityError("Truncated or malformed .sovereign-capsule file")

        magic = capsule_blob[: len(self.MAGIC)]
        if magic != self.MAGIC:
            raise CapsuleIntegrityError(
                f"Invalid capsule magic header: expected {self.MAGIC!r}, got {magic!r}"
            )

        offset = len(self.MAGIC)
        salt = capsule_blob[offset : offset + self.SALT_BYTES]
        offset += self.SALT_BYTES
        nonce = capsule_blob[offset : offset + self.NONCE_BYTES]
        offset += self.NONCE_BYTES
        expected_digest = capsule_blob[offset : offset + self.DIGEST_BYTES]
        offset += self.DIGEST_BYTES

        header = capsule_blob[: self.HEADER_BYTES]
        ciphertext = capsule_blob[self.HEADER_BYTES :]

        key = self._derive_key(passphrase=passphrase, salt=salt)
        aesgcm = AESGCM(key)

        try:
            compressed_bytes = aesgcm.decrypt(nonce, ciphertext, header)
        except InvalidTag as exc:
            raise CapsuleIntegrityError(
                "AES-256-GCM authentication tag verification failed: wrong passphrase or tampered capsule"
            ) from exc
        except Exception as exc:
            raise CapsuleIntegrityError(f"Capsule decryption failed: {exc}") from exc

        try:
            decompressor = zstd.ZstdDecompressor()
            serialized_bytes = decompressor.decompress(compressed_bytes)
        except Exception as exc:
            raise CapsuleIntegrityError(f"Zstandard decompression failed: {exc}") from exc

        actual_digest = hashlib.sha256(serialized_bytes).digest()
        if actual_digest != expected_digest:
            raise CapsuleIntegrityError(
                "SHA-256 manifest digest mismatch after decompression"
            )

        try:
            restored = json.loads(serialized_bytes.decode("utf-8"))
        except Exception as exc:
            raise CapsuleIntegrityError(f"Malformed capsule JSON manifest: {exc}") from exc

        if not isinstance(restored, dict):
            raise CapsuleIntegrityError("Capsule root payload must be a JSON object")

        return restored
