#!/usr/bin/env python3
"""
Task 7.4: Cryptographic Offline Update Packaging (`tools/package_update.py`).
Aegis Sovereign Knowledge Appliance.

Implements air-gapped differential update packaging (`.aegis-update`, `MAGIC = b"AEGISUPD\\x01"`)
combining:
  - Per-file SHA-256 cryptographic digests in a canonical JSON manifest
  - Ed25519 asymmetric signature verification (`cryptography.hazmat.primitives.asymmetric.ed25519`)
    prior to Zstandard payload decompression
  - Strict protection against signature tampering, file hash corruption,
    path traversal (`..` or `/`), and version downgrade attacks (`version <= current_version`).
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import zstandard as zstd
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.license import SovereignLicenseManager


class UpdateIntegrityError(Exception):
    """Raised when an `.aegis-update` package fails Ed25519 signature, hash, path, or version validation."""


def _parse_version_tuple(version_str: str) -> Tuple[int, ...]:
    """Parses a semantic version string (e.g., '2.1.0' or 'v1.4.2') into a comparable integer tuple."""
    if not version_str or not isinstance(version_str, str):
        raise UpdateIntegrityError(f"Invalid version string: {version_str!r}")
    cleaned = version_str.strip().lstrip("vV")
    parts = re.split(r"[.\-+]", cleaned)
    numeric_parts: List[int] = []
    for part in parts:
        if part.isdigit():
            numeric_parts.append(int(part))
        else:
            m = re.match(r"^(\d+)", part)
            if m:
                numeric_parts.append(int(m.group(1)))
    if not numeric_parts:
        raise UpdateIntegrityError(f"Unable to parse numeric version from: {version_str!r}")
    while len(numeric_parts) < 3:
        numeric_parts.append(0)
    return tuple(numeric_parts)


def _validate_safe_relative_path(rel_path: str, target_root: Optional[Path] = None) -> str:
    """
    Validates that a file path inside an update bundle is strictly relative and free of
    path traversal sequences (`..`, leading `/`, backslashes, or null bytes).
    """
    if not rel_path or not isinstance(rel_path, str):
        raise UpdateIntegrityError("Empty or invalid file path in update manifest")
    if "\x00" in rel_path or "\\" in rel_path:
        raise UpdateIntegrityError(f"Illegal character in update file path: {rel_path!r}")
    if rel_path.startswith("/") or rel_path.startswith("~"):
        raise UpdateIntegrityError(f"Absolute path forbidden in update bundle: {rel_path!r}")

    parts = Path(rel_path).parts
    if not parts or ".." in parts or "." in parts:
        raise UpdateIntegrityError(f"Path traversal sequence rejected in update bundle: {rel_path!r}")

    if target_root is not None:
        resolved_root = target_root.resolve()
        resolved_target = (resolved_root / rel_path).resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError as exc:
            raise UpdateIntegrityError(
                f"Path traversal escaped target directory: {rel_path!r}"
            ) from exc

    return "/".join(parts)


class SovereignUpdatePackager:
    """
    Creates, verifies, and applies Ed25519-signed, Zstandard-compressed `.aegis-update` bundles.

    Binary Container Layout:
      - Bytes 0..9   : MAGIC (`b"AEGISUPD\\x01"`)
      - Bytes 9..73  : Ed25519 Signature (64 bytes) over Canonical JSON Manifest
      - Bytes 73..77 : Manifest Length (`uint32` big-endian)
      - Bytes 77..N  : Canonical JSON Manifest (`utf-8` sorted keys, compact separators)
      - Bytes N..EOF : Zstandard-compressed payload (`{"files": {rel_path: base64_bytes}}`)
    """

    MAGIC: bytes = b"AEGISUPD\x01"
    SIGNATURE_BYTES: int = 64
    LENGTH_PREFIX_BYTES: int = 4
    MIN_HEADER_BYTES: int = len(MAGIC) + SIGNATURE_BYTES + LENGTH_PREFIX_BYTES  # 77 bytes
    DEFAULT_ZSTD_LEVEL: int = 10

    def __init__(self, compression_level: int = DEFAULT_ZSTD_LEVEL) -> None:
        self.compression_level = int(compression_level)

    @staticmethod
    def generate_keypair() -> Tuple[bytes, bytes]:
        """Generates an Ed25519 keypair in PEM format compatible with SovereignLicenseManager."""
        return SovereignLicenseManager.generate_keypair()

    @staticmethod
    def _collect_source_files(
        source: Union[str, Path, Dict[str, Union[bytes, str, Path]]],
    ) -> Dict[str, bytes]:
        """Normalizes a source directory or mapping into `{relative_posix_path: raw_bytes}`."""
        collected: Dict[str, bytes] = {}
        if isinstance(source, dict):
            for rel_path, content in source.items():
                safe_rel = _validate_safe_relative_path(str(rel_path))
                if isinstance(content, bytes):
                    raw_bytes = content
                elif isinstance(content, Path):
                    raw_bytes = content.read_bytes()
                elif isinstance(content, str):
                    raw_bytes = content.encode("utf-8")
                else:
                    raise TypeError(f"Unsupported file content type for {rel_path}: {type(content)}")
                collected[safe_rel] = raw_bytes
        else:
            src_dir = Path(source)
            if not src_dir.is_dir():
                raise FileNotFoundError(f"Update source directory not found: {src_dir}")
            for file_path in sorted(src_dir.rglob("*")):
                if file_path.is_file():
                    rel_posix = file_path.relative_to(src_dir).as_posix()
                    safe_rel = _validate_safe_relative_path(rel_posix)
                    collected[safe_rel] = file_path.read_bytes()

        if not collected:
            raise ValueError("Update payload must contain at least one file")
        return collected

    @classmethod
    def create_update_bundle(
        cls,
        source_files: Union[str, Path, Dict[str, Union[bytes, str, Path]]],
        output_path: Union[str, Path],
        version: str,
        private_key_pem: bytes,
        min_required_version: str = "1.0.0",
        changelog: str = "Differential sovereign appliance update",
        created_at: Optional[str] = None,
        compression_level: int = DEFAULT_ZSTD_LEVEL,
    ) -> Dict[str, Any]:
        """
        Packages differential update files into a compressed, Ed25519-signed `.aegis-update` file.
        """
        _parse_version_tuple(version)
        _parse_version_tuple(min_required_version)

        try:
            private_key = serialization.load_pem_private_key(private_key_pem, password=None)
            if not isinstance(private_key, ed25519.Ed25519PrivateKey):
                raise ValueError("Provided private key is not an Ed25519 key")
        except Exception as exc:
            raise UpdateIntegrityError(f"Failed to load Ed25519 private key: {exc}") from exc

        files_map = cls._collect_source_files(source_files)
        files_sha256: Dict[str, str] = {}
        encoded_files: Dict[str, str] = {}
        uncompressed_total = 0

        for rel_path, raw_bytes in sorted(files_map.items()):
            files_sha256[rel_path] = hashlib.sha256(raw_bytes).hexdigest()
            encoded_files[rel_path] = base64.b64encode(raw_bytes).decode("ascii")
            uncompressed_total += len(raw_bytes)

        payload_json = json.dumps(
            {"files": encoded_files},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        compressor = zstd.ZstdCompressor(level=compression_level)
        compressed_payload = compressor.compress(payload_json)
        compressed_payload_sha256 = hashlib.sha256(compressed_payload).hexdigest()

        manifest: Dict[str, Any] = {
            "version": str(version).strip(),
            "min_required_version": str(min_required_version).strip(),
            "created_at": created_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files_sha256": files_sha256,
            "payload_compressed_sha256": compressed_payload_sha256,
            "payload_compressed_bytes": len(compressed_payload),
            "changelog": str(changelog),
        }

        canonical_manifest_bytes = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        signature = private_key.sign(canonical_manifest_bytes)
        manifest_len_prefix = struct.pack(">I", len(canonical_manifest_bytes))

        bundle_bytes = (
            cls.MAGIC
            + signature
            + manifest_len_prefix
            + canonical_manifest_bytes
            + compressed_payload
        )

        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(bundle_bytes)

        return {
            "bundle_path": str(out_file),
            "version": manifest["version"],
            "min_required_version": manifest["min_required_version"],
            "file_count": len(files_sha256),
            "uncompressed_bytes": uncompressed_total,
            "compressed_bytes": len(compressed_payload),
            "bundle_bytes": len(bundle_bytes),
            "signature_hex": signature.hex(),
            "manifest": manifest,
        }

    # Alias for ergonomic usage
    package_update = create_update_bundle

    @classmethod
    def verify_update_bundle(
        cls,
        bundle_path: Union[str, Path],
        public_key_pem: bytes,
        current_version: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bytes]:
        """
        Verifies the `.aegis-update` header, Ed25519 signature, version monotonicity,
        and manifest path safety BEFORE decompressing the Zstandard payload.

        Returns:
            Tuple[Dict[str, Any], bytes]: (verified_manifest_dict, compressed_payload_bytes)
        """
        in_file = Path(bundle_path)
        if not in_file.is_file():
            raise FileNotFoundError(f"Update bundle not found: {in_file}")

        blob = in_file.read_bytes()
        if len(blob) < cls.MIN_HEADER_BYTES:
            raise UpdateIntegrityError("Truncated or malformed .aegis-update container")

        magic = blob[: len(cls.MAGIC)]
        if magic != cls.MAGIC:
            raise UpdateIntegrityError(
                f"Invalid update magic header: expected {cls.MAGIC!r}, got {magic!r}"
            )

        offset = len(cls.MAGIC)
        signature = blob[offset : offset + cls.SIGNATURE_BYTES]
        offset += cls.SIGNATURE_BYTES

        (manifest_len,) = struct.unpack(">I", blob[offset : offset + cls.LENGTH_PREFIX_BYTES])
        offset += cls.LENGTH_PREFIX_BYTES

        if manifest_len <= 0 or offset + manifest_len > len(blob):
            raise UpdateIntegrityError("Corrupted manifest length in .aegis-update header")

        canonical_manifest_bytes = blob[offset : offset + manifest_len]
        compressed_payload = blob[offset + manifest_len :]

        # 1. Load Ed25519 public key
        try:
            public_key = serialization.load_pem_public_key(public_key_pem)
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                raise ValueError("Supplied key is not an Ed25519 public key")
        except Exception as exc:
            raise UpdateIntegrityError(f"Invalid Ed25519 public key: {exc}") from exc

        # 2. Verify Ed25519 cryptographic signature BEFORE decompressing any payload bytes
        try:
            public_key.verify(signature, canonical_manifest_bytes)
        except InvalidSignature as exc:
            raise UpdateIntegrityError(
                "Ed25519 cryptographic signature verification failed (tampered update rejected)"
            ) from exc
        except Exception as exc:
            raise UpdateIntegrityError(f"Signature verification error: {exc}") from exc

        # 3. Parse and validate canonical manifest structure
        try:
            manifest = json.loads(canonical_manifest_bytes.decode("utf-8"))
        except Exception as exc:
            raise UpdateIntegrityError(f"Malformed JSON manifest: {exc}") from exc

        if not isinstance(manifest, dict) or "version" not in manifest or "files_sha256" not in manifest:
            raise UpdateIntegrityError("Manifest missing required fields ('version', 'files_sha256')")

        # v2 Hardening: Verify compressed Zstandard ciphertext SHA-256 BEFORE calling zstd.decompress()
        expected_comp_sha = manifest.get("payload_compressed_sha256")
        if expected_comp_sha:
            actual_comp_sha = hashlib.sha256(compressed_payload).hexdigest()
            if actual_comp_sha != expected_comp_sha:
                raise UpdateIntegrityError(
                    "Compressed Zstandard payload SHA-256 mismatch (pre-decompression tamper rejected)"
                )

        # 4. Enforce version anti-downgrade & min_required_version rules
        target_ver = _parse_version_tuple(str(manifest["version"]))
        min_req_ver = _parse_version_tuple(str(manifest.get("min_required_version", "0.0.0")))

        if current_version is not None:
            curr_ver = _parse_version_tuple(str(current_version))
            if target_ver <= curr_ver:
                raise UpdateIntegrityError(
                    f"Version downgrade attack rejected: bundle version {manifest['version']} "
                    f"<= current appliance version {current_version}"
                )
            if curr_ver < min_req_ver:
                raise UpdateIntegrityError(
                    f"Appliance version {current_version} is older than min_required_version "
                    f"{manifest.get('min_required_version')}"
                )

        # 5. Validate all manifest file paths against path traversal before decompression
        files_sha256 = manifest["files_sha256"]
        if not isinstance(files_sha256, dict) or not files_sha256:
            raise UpdateIntegrityError("Manifest 'files_sha256' must be a non-empty mapping")

        for rel_path in files_sha256.keys():
            _validate_safe_relative_path(str(rel_path))

        return manifest, compressed_payload

    @classmethod
    def verify_and_apply_update(
        cls,
        bundle_path: Union[str, Path],
        public_key_pem: bytes,
        target_dir: Union[str, Path],
        current_version: str = "1.0.0",
    ) -> Dict[str, Any]:
        """
        Verifies the Ed25519 signature, anti-downgrade version policy, path safety,
        and per-file SHA-256 digests before applying an update to `target_dir`.
        """
        target_root = Path(target_dir)

        # Steps 1-5: Verify signature, anti-downgrade, and manifest paths prior to decompression
        manifest, compressed_payload = cls.verify_update_bundle(
            bundle_path=bundle_path,
            public_key_pem=public_key_pem,
            current_version=current_version,
        )

        # Step 6: Decompress Zstandard payload
        try:
            decompressor = zstd.ZstdDecompressor()
            payload_bytes = decompressor.decompress(compressed_payload)
            payload_obj = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise UpdateIntegrityError(
                f"Zstandard payload decompression failed (corrupted payload): {exc}"
            ) from exc

        encoded_files = payload_obj.get("files") if isinstance(payload_obj, dict) else None
        if not isinstance(encoded_files, dict):
            raise UpdateIntegrityError("Decompressed update payload missing 'files' dictionary")

        expected_hashes: Dict[str, str] = manifest["files_sha256"]

        # Ensure exact correspondence between manifest file list and payload file list
        if set(encoded_files.keys()) != set(expected_hashes.keys()):
            raise UpdateIntegrityError(
                "Mismatch between manifest file list and payload file entries"
            )

        # Step 7: Verify every file's relative path and SHA-256 hash in memory BEFORE writing to disk
        verified_files: Dict[str, bytes] = {}
        for rel_path, b64_content in encoded_files.items():
            safe_rel = _validate_safe_relative_path(rel_path, target_root=target_root)
            try:
                raw_bytes = base64.b64decode(b64_content.encode("ascii"))
            except Exception as exc:
                raise UpdateIntegrityError(f"Invalid base64 encoding for file {rel_path}: {exc}") from exc

            actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
            expected_sha256 = expected_hashes[rel_path]
            if actual_sha256 != expected_sha256:
                raise UpdateIntegrityError(
                    f"SHA-256 digest mismatch for '{rel_path}': expected {expected_sha256}, got {actual_sha256}"
                )
            verified_files[safe_rel] = raw_bytes

        # Step 8: Write verified files to target directory
        target_root.mkdir(parents=True, exist_ok=True)
        applied_files: List[str] = []
        for safe_rel, raw_bytes in sorted(verified_files.items()):
            dest_file = target_root / safe_rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(raw_bytes)
            applied_files.append(safe_rel)

        return {
            "status": "applied",
            "version": manifest["version"],
            "previous_version": current_version,
            "applied_files": applied_files,
            "file_count": len(applied_files),
            "changelog": manifest.get("changelog", ""),
        }


def verify_and_apply_update(
    bundle_path: Union[str, Path],
    public_key_pem: bytes,
    target_dir: Union[str, Path],
    current_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Module-level convenience function for `SovereignUpdatePackager.verify_and_apply_update`."""
    return SovereignUpdatePackager.verify_and_apply_update(
        bundle_path=bundle_path,
        public_key_pem=public_key_pem,
        target_dir=target_dir,
        current_version=current_version,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aegis Sovereign Appliance — Cryptographic Offline Update Packager (.aegis-update)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--create", action="store_true", help="Create a signed .aegis-update bundle")
    mode.add_argument("--verify", action="store_true", help="Verify an .aegis-update bundle signature")
    mode.add_argument("--apply", action="store_true", help="Verify and apply an .aegis-update bundle")

    parser.add_argument("--source-dir", type=Path, help="Source directory of files to package (--create)")
    parser.add_argument("--bundle", type=Path, required=True, help="Path to .aegis-update file")
    parser.add_argument("--private-key", type=Path, help="Path to Ed25519 private key PEM (--create)")
    parser.add_argument("--public-key", type=Path, help="Path to Ed25519 public key PEM (--verify / --apply)")
    parser.add_argument("--target-dir", type=Path, help="Target installation directory (--apply)")
    parser.add_argument("--version", type=str, default="2.0.0", help="Update version string (--create)")
    parser.add_argument(
        "--min-required-version",
        type=str,
        default="1.0.0",
        help="Minimum required appliance version (--create)",
    )
    parser.add_argument(
        "--current-version",
        type=str,
        default="1.0.0",
        help="Current installed appliance version (--verify / --apply)",
    )
    parser.add_argument(
        "--changelog",
        type=str,
        default="Differential sovereign appliance update",
        help="Changelog description (--create)",
    )

    args = parser.parse_args(argv)

    if args.create:
        if not args.source_dir or not args.private_key:
            parser.error("--create requires --source-dir and --private-key")
        priv_pem = args.private_key.read_bytes()
        result = SovereignUpdatePackager.create_update_bundle(
            source_files=args.source_dir,
            output_path=args.bundle,
            version=args.version,
            private_key_pem=priv_pem,
            min_required_version=args.min_required_version,
            changelog=args.changelog,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.verify:
        if not args.public_key:
            parser.error("--verify requires --public-key")
        pub_pem = args.public_key.read_bytes()
        manifest, _ = SovereignUpdatePackager.verify_update_bundle(
            bundle_path=args.bundle,
            public_key_pem=pub_pem,
            current_version=args.current_version,
        )
        print(json.dumps({"status": "verified", "manifest": manifest}, indent=2))
        return 0

    if args.apply:
        if not args.public_key or not args.target_dir:
            parser.error("--apply requires --public-key and --target-dir")
        pub_pem = args.public_key.read_bytes()
        result = SovereignUpdatePackager.verify_and_apply_update(
            bundle_path=args.bundle,
            public_key_pem=pub_pem,
            target_dir=args.target_dir,
            current_version=args.current_version,
        )
        print(json.dumps(result, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
