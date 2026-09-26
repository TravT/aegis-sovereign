#!/usr/bin/env python3
"""
Automated Pytest Suite for Tasks 7.3 & 7.4:
  - `tools/benchmark_generator.py` (`SyntheticCorpusGenerator`)
  - `tools/package_update.py` (`SovereignUpdatePackager`, `UpdateIntegrityError`, `verify_and_apply_update`)
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest
import zstandard as zstd
from cryptography.hazmat.primitives import serialization

AEGIS_ROOT = Path(__file__).resolve().parent.parent
if str(AEGIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AEGIS_ROOT))

from core.containers import SovereignArchiveStreamer
from core.router import SovereignQueryRouter
from tools.benchmark_generator import SyntheticCorpusGenerator, main as benchmark_cli_main
from tools.package_update import (
    SovereignUpdatePackager,
    UpdateIntegrityError,
    main as update_cli_main,
    verify_and_apply_update,
)


# ==============================================================================
# Task 7.3 Tests: Synthetic Multi-Tier Benchmark Dataset Generator
# ==============================================================================


def test_benchmark_generator_free_tier_domains_and_needles(tmp_path: Path) -> None:
    gen = SyntheticCorpusGenerator(seed=101)
    manifest = gen.generate(output_dir=tmp_path, tier="free", count=8)

    assert manifest["tier"] == "free"
    assert manifest["tier_capacity"] == 100
    assert manifest["document_count"] == 8
    assert set(manifest["domains"]) == {"pharmacy", "medical", "telco", "legal_tax"}
    assert len(manifest["prong1_exact_needles"]) == 8
    assert len(manifest["prong2_analytical_queries"]) == 8
    assert manifest["archives"] == []

    # Verify domain identifiers in generated files
    all_identifiers = [
        ident for doc in manifest["documents"] for ident in doc["exact_identifiers"]
    ]
    assert any(i.startswith("LOTE-2026-") for i in all_identifiers)
    assert "Portaria 344/98" in all_identifiers
    assert any(i.startswith("CID-10:") for i in all_identifiers)
    assert any(i.startswith("CRM-SP") for i in all_identifiers)
    assert "3GPP TS 38.331" in all_identifiers
    assert any(i.startswith("ALM-262") for i in all_identifiers)
    assert any(i.startswith("DARF-") for i in all_identifiers)

    # Verify SovereignQueryRouter extracts identifiers and routes Prong 1 needles
    router = SovereignQueryRouter()
    try:
        for needle in manifest["prong1_exact_needles"]:
            decision = router.analyze_query(needle["query"])
            assert decision.extracted_identifier is not None
            assert decision.bypass_vector_search is True
    finally:
        router.close()


def test_benchmark_generator_pro_and_enterprise_tiers(tmp_path: Path) -> None:
    gen = SyntheticCorpusGenerator(seed=2026)

    pro_dir = tmp_path / "pro_corpus"
    pro_manifest = gen.generate(output_dir=pro_dir, tier="pro", count=8)
    assert pro_manifest["tier"] == "pro"
    assert pro_manifest["tier_capacity"] == 5000
    assert len(pro_manifest["archives"]) == 2
    assert len(pro_manifest["graph_ground_truth_edges"]) >= 16

    # Verify .hdx archive can be streamed in-memory by SovereignArchiveStreamer
    hdx_rel = [a["archive_path"] for a in pro_manifest["archives"] if a["format"] == "hdx"][0]
    streamer = SovereignArchiveStreamer()
    streamed = list(streamer.stream_archive(pro_dir / hdx_rel))
    assert len(streamed) == 4

    ent_dir = tmp_path / "enterprise_corpus"
    ent_manifest = gen.generate(output_dir=ent_dir, tier="enterprise", count=12)
    assert ent_manifest["tier"] == "enterprise"
    assert ent_manifest["tier_capacity"] == 25000
    assert len(ent_manifest["enterprise_stress_needles"]) >= 8


def test_benchmark_generator_cli(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_out"
    rc = benchmark_cli_main(["--tier", "pro", "--count", "4", "--output-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "manifest.json").is_file()


# ==============================================================================
# Task 7.4 Tests: Cryptographic Offline Update Packaging (.aegis-update)
# ==============================================================================


def test_update_packager_valid_create_and_apply(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()

    payload_files = {
        "core/router/patch_v2.py": b"# Patch v2.1.0\nROUTER_PATCH_ACTIVE = True\n",
        "data/telemetry/fleet_v2.zstd_dict": b"ZSTD_DICT_BINARY_PAYLOAD_V2",
        "data/grammars/pharmacy_anvisa.json": '{"portaria": "344/98", "strict": true}\n',
    }

    bundle_path = tmp_path / "update_v2.1.0.aegis-update"
    meta = SovereignUpdatePackager.create_update_bundle(
        source_files=payload_files,
        output_path=bundle_path,
        version="2.1.0",
        private_key_pem=priv_pem,
        min_required_version="1.0.0",
        changelog="Add ANVISA Portaria 344/98 grammar and router optimization",
    )

    assert bundle_path.is_file()
    assert bundle_path.read_bytes().startswith(SovereignUpdatePackager.MAGIC)
    assert meta["file_count"] == 3

    target_dir = tmp_path / "installed_appliance"
    applied = verify_and_apply_update(
        bundle_path=bundle_path,
        public_key_pem=pub_pem,
        target_dir=target_dir,
        current_version="1.5.0",
    )

    assert applied["status"] == "applied"
    assert applied["version"] == "2.1.0"
    assert (target_dir / "core/router/patch_v2.py").read_bytes() == payload_files["core/router/patch_v2.py"]
    assert (
        target_dir / "data/telemetry/fleet_v2.zstd_dict"
    ).read_bytes() == payload_files["data/telemetry/fleet_v2.zstd_dict"]


def test_update_packager_rejects_tampered_signature_and_manifest(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()
    bundle_path = tmp_path / "valid.aegis-update"

    SovereignUpdatePackager.create_update_bundle(
        source_files={"core/module.py": b"print('sovereign')\n"},
        output_path=bundle_path,
        version="2.0.0",
        private_key_pem=priv_pem,
    )

    raw = bytearray(bundle_path.read_bytes())
    # Flip a bit inside the 64-byte Ed25519 signature (offset 15)
    raw[15] ^= 0xFF
    tampered_path = tmp_path / "tampered_sig.aegis-update"
    tampered_path.write_bytes(bytes(raw))

    with pytest.raises(UpdateIntegrityError, match="signature verification failed"):
        verify_and_apply_update(
            bundle_path=tampered_path,
            public_key_pem=pub_pem,
            target_dir=tmp_path / "out",
            current_version="1.0.0",
        )


def test_update_packager_rejects_wrong_public_key(tmp_path: Path) -> None:
    priv_pem_1, _ = SovereignUpdatePackager.generate_keypair()
    _, pub_pem_2 = SovereignUpdatePackager.generate_keypair()

    bundle_path = tmp_path / "signed_by_key1.aegis-update"
    SovereignUpdatePackager.create_update_bundle(
        source_files={"core/module.py": b"x = 1\n"},
        output_path=bundle_path,
        version="2.0.0",
        private_key_pem=priv_pem_1,
    )

    with pytest.raises(UpdateIntegrityError, match="signature verification failed"):
        verify_and_apply_update(
            bundle_path=bundle_path,
            public_key_pem=pub_pem_2,
            target_dir=tmp_path / "out",
            current_version="1.0.0",
        )


def test_update_packager_rejects_corrupted_file_hash(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()
    private_key = serialization.load_pem_private_key(priv_pem, password=None)

    # Construct a bundle whose Ed25519 manifest signature is valid, but whose file content
    # inside the Zstandard stream has been altered so its SHA-256 does not match files_sha256
    manifest = {
        "version": "2.0.0",
        "min_required_version": "1.0.0",
        "created_at": "2026-09-24T12:00:00+00:00",
        "files_sha256": {
            "core/engine.py": hashlib.sha256(b"EXPECTED_CLEAN_CODE").hexdigest(),
        },
        "changelog": "Test corrupted file hash detection",
    }
    canonical_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(canonical_manifest)

    corrupted_payload = json.dumps(
        {"files": {"core/engine.py": base64.b64encode(b"CORRUPTED_MALICIOUS_CODE").decode("ascii")}}
    ).encode("utf-8")
    compressed_payload = zstd.ZstdCompressor().compress(corrupted_payload)

    bundle_bytes = (
        SovereignUpdatePackager.MAGIC
        + signature
        + struct.pack(">I", len(canonical_manifest))
        + canonical_manifest
        + compressed_payload
    )
    corrupted_bundle = tmp_path / "corrupted_hash.aegis-update"
    corrupted_bundle.write_bytes(bundle_bytes)

    target_dir = tmp_path / "target_clean"
    with pytest.raises(UpdateIntegrityError, match="SHA-256 digest mismatch"):
        verify_and_apply_update(
            bundle_path=corrupted_bundle,
            public_key_pem=pub_pem,
            target_dir=target_dir,
            current_version="1.0.0",
        )
    assert not (target_dir / "core/engine.py").exists()


def test_update_packager_rejects_path_traversal(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()
    private_key = serialization.load_pem_private_key(priv_pem, password=None)

    # 1. Reject at creation time
    with pytest.raises(UpdateIntegrityError, match="Path traversal|Absolute path"):
        SovereignUpdatePackager.create_update_bundle(
            source_files={"../../etc/passwd": b"root:x:0:0"},
            output_path=tmp_path / "bad.aegis-update",
            version="2.0.0",
            private_key_pem=priv_pem,
        )

    # 2. Reject forged signed manifest containing `..` traversal
    evil_manifest = {
        "version": "2.0.0",
        "min_required_version": "1.0.0",
        "created_at": "2026-09-24T12:00:00+00:00",
        "files_sha256": {
            "../escape.py": hashlib.sha256(b"pwn").hexdigest(),
        },
        "changelog": "Traversal test",
    }
    canonical_manifest = json.dumps(evil_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = private_key.sign(canonical_manifest)
    comp = zstd.ZstdCompressor().compress(
        json.dumps({"files": {"../escape.py": base64.b64encode(b"pwn").decode("ascii")}}).encode("utf-8")
    )
    evil_bundle = tmp_path / "evil_traversal.aegis-update"
    evil_bundle.write_bytes(
        SovereignUpdatePackager.MAGIC + sig + struct.pack(">I", len(canonical_manifest)) + canonical_manifest + comp
    )

    with pytest.raises(UpdateIntegrityError, match="Path traversal"):
        verify_and_apply_update(
            bundle_path=evil_bundle,
            public_key_pem=pub_pem,
            target_dir=tmp_path / "install_root",
            current_version="1.0.0",
        )


def test_update_packager_rejects_version_downgrade_attack(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()
    bundle_path = tmp_path / "old_v1.2.0.aegis-update"

    SovereignUpdatePackager.create_update_bundle(
        source_files={"core/patch.py": b"VERSION = '1.2.0'\n"},
        output_path=bundle_path,
        version="1.2.0",
        private_key_pem=priv_pem,
    )

    # Attempting to apply v1.2.0 over v2.0.0 (or same version v1.2.0) must fail
    with pytest.raises(UpdateIntegrityError, match="downgrade attack rejected"):
        verify_and_apply_update(
            bundle_path=bundle_path,
            public_key_pem=pub_pem,
            target_dir=tmp_path / "target",
            current_version="2.0.0",
        )

    with pytest.raises(UpdateIntegrityError, match="downgrade attack rejected"):
        verify_and_apply_update(
            bundle_path=bundle_path,
            public_key_pem=pub_pem,
            target_dir=tmp_path / "target",
            current_version="1.2.0",
        )


def test_update_packager_cli_workflow(tmp_path: Path) -> None:
    priv_pem, pub_pem = SovereignUpdatePackager.generate_keypair()
    priv_file = tmp_path / "ed25519_priv.pem"
    pub_file = tmp_path / "ed25519_pub.pem"
    priv_file.write_bytes(priv_pem)
    pub_file.write_bytes(pub_pem)

    src_dir = tmp_path / "src_payload"
    (src_dir / "core").mkdir(parents=True)
    (src_dir / "core" / "feature.py").write_text("FEATURE = True\n", encoding="utf-8")

    bundle_file = tmp_path / "cli_bundle.aegis-update"
    target_dir = tmp_path / "cli_target"

    assert (
        update_cli_main(
            [
                "--create",
                "--source-dir",
                str(src_dir),
                "--bundle",
                str(bundle_file),
                "--private-key",
                str(priv_file),
                "--version",
                "2.5.0",
            ]
        )
        == 0
    )
    assert (
        update_cli_main(
            [
                "--verify",
                "--bundle",
                str(bundle_file),
                "--public-key",
                str(pub_file),
                "--current-version",
                "2.0.0",
            ]
        )
        == 0
    )
    assert (
        update_cli_main(
            [
                "--apply",
                "--bundle",
                str(bundle_file),
                "--public-key",
                str(pub_file),
                "--target-dir",
                str(target_dir),
                "--current-version",
                "2.0.0",
            ]
        )
        == 0
    )
    assert (target_dir / "core" / "feature.py").read_text(encoding="utf-8") == "FEATURE = True\n"
