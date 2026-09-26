"""Automated Pytest Suite for ADR-07 Virtual Container Streaming & ADR-08 Onboarding/Capsules."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest
import zstandard as zstd

from core.containers import (
    ArchiveEntry,
    ArchiveSecurityError,
    SovereignArchiveStreamer,
)
from core.onboarding import DirectoryCandidate, OnboardingRadar
from tools.capsule import CapsuleIntegrityError, SovereignCapsuleManager


# ---------------------------------------------------------------------------
# Helpers for building synthetic archives in-memory
# ---------------------------------------------------------------------------

def _create_zip_file(zip_path: Path, files: dict[str, bytes]) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    zip_path.write_bytes(buf.getvalue())


def _create_tar_zst_file(tar_zst_path: Path, files: dict[str, bytes]) -> None:
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    cctx = zstd.ZstdCompressor(level=6)
    compressed = cctx.compress(tar_buf.getvalue())
    tar_zst_path.write_bytes(compressed)


# ---------------------------------------------------------------------------
# 1. In-memory .zip, .tar.zst, .epub, and .hdx streaming & Virtual URI tests
# ---------------------------------------------------------------------------

def test_in_memory_zip_and_tar_zst_streaming_and_virtual_uri(tmp_path: Path) -> None:
    """Verify .zip and .tar.zst stream purely in-memory and resolve archive:// URIs without disk extraction."""
    streamer = SovereignArchiveStreamer()

    # 1a. Create .zip archive
    zip_file = tmp_path / "telecom_manuals.zip"
    doc_a = b"Huawei S6730 Alarm 0x40000001: Optical module LOS detected on XGigabitEthernet0/0/1."
    doc_b = b"<html><body><h1>BGP Peer Flapping</h1><p>Check hold timer and MTU.</p></body></html>"
    _create_zip_file(
        zip_file,
        {
            "alarms/0x40000001.txt": doc_a,
            "runbooks/bgp_flapping.html": doc_b,
        },
    )

    before_files = set(tmp_path.rglob("*"))
    entries = list(streamer.stream_archive(zip_file))
    after_files = set(tmp_path.rglob("*"))

    # Zero temporary files extracted to disk
    assert before_files == after_files
    assert len(entries) == 2

    by_name = {e.entry_name: e for e in entries}
    alarm_entry = by_name["alarms/0x40000001.txt"]
    assert isinstance(alarm_entry, ArchiveEntry)
    assert alarm_entry.virtual_uri == f"archive://{zip_file}#alarms/0x40000001.txt"
    assert alarm_entry.uncompressed_size == len(doc_a)
    assert alarm_entry.sha256_hash == hashlib.sha256(doc_a).hexdigest()
    assert "Optical module LOS" in alarm_entry.content_text

    html_entry = by_name["runbooks/bgp_flapping.html"]
    assert "BGP Peer Flapping" in html_entry.content_text
    assert "<html>" not in html_entry.content_text

    # Resolve specific virtual URI directly from in-memory archive stream
    resolved = streamer.resolve_virtual_uri(f"archive://{zip_file}#alarms/0x40000001.txt")
    assert resolved.entry_name == "alarms/0x40000001.txt"
    assert resolved.sha256_hash == alarm_entry.sha256_hash
    assert resolved.content_text == alarm_entry.content_text
    assert set(tmp_path.rglob("*")) == before_files

    # 1b. Create .tar.zst archive
    tar_zst_file = tmp_path / "contracts_bundle.tar.zst"
    clause_text = (
        b"CL\xc3\x81USULA OITAVA - CONFIDENCIALIDADE E SOBERANIA DE DADOS (LGPD Art. 46).\n"
        b"Todo processamento devera ocorrer em appliance air-gapped local."
    )
    _create_tar_zst_file(
        tar_zst_file,
        {"contracts/2026/nda_enterprise.md": clause_text},
    )

    tar_entries = list(streamer.stream_archive(tar_zst_file))
    assert len(tar_entries) == 1
    tar_entry = tar_entries[0]
    assert tar_entry.virtual_uri == f"archive://{tar_zst_file}#contracts/2026/nda_enterprise.md"
    assert tar_entry.uncompressed_size == len(clause_text)
    assert tar_entry.sha256_hash == hashlib.sha256(clause_text).hexdigest()
    assert "LGPD Art. 46" in tar_entry.content_text

    resolved_tar = streamer.resolve_virtual_uri(tar_entry.virtual_uri)
    assert resolved_tar.sha256_hash == tar_entry.sha256_hash
    assert "appliance air-gapped local" in resolved_tar.content_text


def test_hdx_and_epub_container_streaming(tmp_path: Path) -> None:
    """Verify .hdx (HedEx) and .epub containers stream XHTML/XML content cleanly in memory."""
    streamer = SovereignArchiveStreamer()

    hdx_path = tmp_path / "S6730_V200R021.hdx"
    _create_zip_file(
        hdx_path,
        {
            "profile.xml": b"<profile><model>S6730-H48X6C</model><version>V200R021C00</version></profile>",
            "resources/topic_01.xhtml": b"<html><body><h2>display interface brief</h2><p>Shows port link state.</p></body></html>",
        },
    )
    hdx_entries = list(streamer.stream_archive(hdx_path))
    assert len(hdx_entries) == 2
    topic = streamer.resolve_virtual_uri(f"archive://{hdx_path}#resources/topic_01.xhtml")
    assert "display interface brief" in topic.content_text
    assert "<h2>" not in topic.content_text

    epub_path = tmp_path / "clinical_protocol.epub"
    _create_zip_file(
        epub_path,
        {
            "mimetype": b"application/epub+zip",
            "META-INF/container.xml": b"<container/>",
            "OEBPS/chapter1.xhtml": b"<html><body><h1>Protocolo Cardiovascular</h1><p>Troponina I de alta sensibilidade.</p></body></html>",
        },
    )
    epub_entries = list(streamer.stream_archive(epub_path))
    assert len(epub_entries) == 1
    assert epub_entries[0].entry_name == "OEBPS/chapter1.xhtml"
    assert "Troponina I" in epub_entries[0].content_text


# ---------------------------------------------------------------------------
# 2. Zip-Bomb Detection (>100:1 compression ratio & size limits)
# ---------------------------------------------------------------------------

def test_zip_bomb_compression_ratio_rejected(tmp_path: Path) -> None:
    """Verify that an archive entry exceeding the 100:1 compression ratio raises ArchiveSecurityError."""
    streamer = SovereignArchiveStreamer(max_compression_ratio=100.0)
    bomb_zip = tmp_path / "zip_bomb_1000x.zip"

    # 2 MB of repetitive null bytes compresses with Deflate to ~2 KB (~1000:1 ratio > 100:1)
    highly_compressible_payload = b"A" * (2 * 1024 * 1024)
    _create_zip_file(bomb_zip, {"bomb_payload.txt": highly_compressible_payload})

    with pytest.raises(ArchiveSecurityError, match="Zip-bomb compression ratio exceeded"):
        list(streamer.stream_archive(bomb_zip))

    with pytest.raises(ArchiveSecurityError, match="Zip-bomb compression ratio exceeded"):
        streamer.resolve_virtual_uri(f"archive://{bomb_zip}#bomb_payload.txt")


def test_entry_size_limit_rejected(tmp_path: Path) -> None:
    """Verify that an entry exceeding max_entry_bytes is rejected with ArchiveSecurityError."""
    import os as _os

    streamer = SovereignArchiveStreamer(max_entry_bytes=4096)
    oversized_zip = tmp_path / "oversized_entry.zip"
    # Incompressible random bytes so ratio is ~1:1, testing max_entry_bytes specifically
    random_payload = _os.urandom(8192)
    _create_zip_file(oversized_zip, {"random.bin": random_payload})

    with pytest.raises(ArchiveSecurityError, match="max_entry_bytes"):
        list(streamer.stream_archive(oversized_zip))


# ---------------------------------------------------------------------------
# 3. Archive Path Traversal Rejection (`../../etc/passwd` & leading `/`)
# ---------------------------------------------------------------------------

def test_archive_path_traversal_rejected(tmp_path: Path) -> None:
    """Verify `../../etc/passwd` and `/etc/shadow` inside archives raise ArchiveSecurityError."""
    streamer = SovereignArchiveStreamer()

    traversal_zip = tmp_path / "malicious_traversal.zip"
    _create_zip_file(
        traversal_zip,
        {"../../etc/passwd": b"root:x:0:0:root:/root:/bin/bash"},
    )

    with pytest.raises(ArchiveSecurityError, match="Path traversal detected in archive entry"):
        list(streamer.stream_archive(traversal_zip))

    abs_path_tar = tmp_path / "malicious_abs.tar.zst"
    _create_tar_zst_file(
        abs_path_tar,
        {"/etc/shadow": b"root:*:19000:0:99999:7:::"},
    )

    with pytest.raises(ArchiveSecurityError, match="Path traversal detected in archive entry"):
        list(streamer.stream_archive(abs_path_tar))


# ---------------------------------------------------------------------------
# 4. 60-Second OnboardingRadar Scanning & Domain Classification
# ---------------------------------------------------------------------------

def test_onboarding_radar_scanning_and_domain_scoring(tmp_path: Path) -> None:
    """Verify OnboardingRadar skips noisy directories, classifies domains, and ranks candidates."""
    # Create noisy directories that MUST be ignored
    noisy_git = tmp_path / ".git" / "objects"
    noisy_git.mkdir(parents=True)
    (noisy_git / "should_ignore.xml").write_text("<xml/>", encoding="utf-8")

    noisy_nm = tmp_path / "node_modules" / "pkg"
    noisy_nm.mkdir(parents=True)
    (noisy_nm / "readme.md").write_text("# Ignored package", encoding="utf-8")

    noisy_venv = tmp_path / ".venv" / "lib"
    noisy_venv.mkdir(parents=True)
    (noisy_venv / "ignored.txt").write_text("venv data", encoding="utf-8")

    # 1. Fiscal NFe directory
    fiscal_dir = tmp_path / "Notas_Fiscais_NFe_2026"
    fiscal_dir.mkdir()
    for i in range(5):
        (fiscal_dir / f"nfe_danfe_{i}.xml").write_text(
            "<nfeProc><NFe><infNFe>ICMS CFOP 5102</infNFe></NFe></nfeProc>" * 10,
            encoding="utf-8",
        )
    (fiscal_dir / "sped_resumo.pdf").write_bytes(b"%PDF-1.4 SPED Fiscal Summary" * 20)

    # 2. Medical Clinical directory
    medical_dir = tmp_path / "Prontuarios_Clinica_Longevity"
    medical_dir.mkdir()
    for i in range(4):
        (medical_dir / f"laudo_paciente_{i}.pdf").write_bytes(b"%PDF-1.4 Clinical Lab Results" * 25)
    (medical_dir / "anvisa_protocol.md").write_text("# Protocolo Clinico ANVISA", encoding="utf-8")

    # 3. Legal Contracts directory
    legal_dir = tmp_path / "Juridico_Contratos_NDA"
    legal_dir.mkdir()
    for i in range(3):
        (legal_dir / f"contrato_aditivo_{i}.docx").write_bytes(b"PK\x03\x04 Clausula LGPD" * 30)

    # 4. Engineering Manuals directory
    eng_dir = tmp_path / "Telecom_Engineering_Manuals"
    eng_dir.mkdir()
    (eng_dir / "Huawei_S6730_Manual.hdx").write_bytes(b"PK\x03\x04 HedEx Manual" * 40)
    (eng_dir / "router_datasheet.pdf").write_bytes(b"%PDF-1.4 Router Datasheet" * 20)

    radar = OnboardingRadar()
    candidates = radar.scan_workspace(root_paths=[tmp_path], max_scan_seconds=60.0)

    discovered_paths = {Path(c.path).name: c for c in candidates}

    # Verify noisy directories were strictly skipped
    assert "objects" not in discovered_paths
    assert "pkg" not in discovered_paths
    assert "lib" not in discovered_paths
    assert ".git" not in discovered_paths
    assert "node_modules" not in discovered_paths
    assert ".venv" not in discovered_paths

    # Verify all 4 vertical folders were discovered and accurately classified
    assert discovered_paths["Notas_Fiscais_NFe_2026"].domain_category == "fiscal_nfe"
    assert discovered_paths["Prontuarios_Clinica_Longevity"].domain_category == "medical_clinical"
    assert discovered_paths["Juridico_Contratos_NDA"].domain_category == "legal_contracts"
    assert discovered_paths["Telecom_Engineering_Manuals"].domain_category == "engineering_manuals"

    # Verify priority scores are bounded [0.0, 100.0] and sorted descending
    scores = [c.priority_score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    for c in candidates:
        assert isinstance(c, DirectoryCandidate)
        assert 0.0 < c.priority_score <= 100.0
        assert c.file_count > 0
        assert c.total_bytes > 0


# ---------------------------------------------------------------------------
# 5. .sovereign-capsule AES-256-GCM + Zstandard Round-Trip & Tamper Rejection
# ---------------------------------------------------------------------------

def test_sovereign_capsule_roundtrip_and_tamper_rejection(tmp_path: Path) -> None:
    """Verify AES-256-GCM + Zstandard capsule export/import and tamper/wrong-passphrase detection."""
    manager = SovereignCapsuleManager()
    capsule_file = tmp_path / "vault_backup.sovereign-capsule"
    passphrase = "Sovereign-Zero-Trust-Passphrase-2026!"

    payload = {
        "capsule_version": "1.0.0",
        "node_id": "aegis-workstation-01",
        "documents": [
            {
                "doc_id": "doc-001",
                "virtual_uri": "archive:///data/manuals.hdx#alarms/0x40000001.html",
                "title": "Optical Module LOS Troubleshooting",
                "tokens_saved": 14500,
            },
            {
                "doc_id": "doc-002",
                "virtual_uri": "file:///data/contracts/nda_2026.pdf",
                "title": "Enterprise Mutual NDA",
                "tokens_saved": 8200,
            },
        ],
        "graph_edges": [
            {"source": "Switch-S6730", "relation": "triggers_alarm", "target": "0x40000001"},
        ],
    }

    export_meta = manager.export_capsule(
        payload_dict=payload,
        output_path=capsule_file,
        passphrase=passphrase,
    )

    assert capsule_file.exists()
    raw_capsule = capsule_file.read_bytes()
    assert raw_capsule.startswith(SovereignCapsuleManager.MAGIC)
    assert export_meta["algorithm"] == "AES-256-GCM+ZSTD"
    assert export_meta["iterations"] == 200_000
    assert len(export_meta["manifest_sha256"]) == 64

    # Successful import with valid passphrase
    restored = manager.import_capsule(capsule_path=capsule_file, passphrase=passphrase)
    assert restored == payload

    # Wrong passphrase must raise CapsuleIntegrityError
    with pytest.raises(CapsuleIntegrityError, match="wrong passphrase or tampered capsule"):
        manager.import_capsule(capsule_path=capsule_file, passphrase="Wrong-Passphrase-123")

    # Tampered ciphertext byte must raise CapsuleIntegrityError
    tampered_cipher_path = tmp_path / "tampered_cipher.sovereign-capsule"
    mutated = bytearray(raw_capsule)
    mutated[-1] ^= 0xFF  # Flip bits in GCM tag / ciphertext
    tampered_cipher_path.write_bytes(bytes(mutated))

    with pytest.raises(CapsuleIntegrityError):
        manager.import_capsule(capsule_path=tampered_cipher_path, passphrase=passphrase)

    # Tampered authenticated header (manifest SHA-256 digest in AAD) must raise CapsuleIntegrityError
    tampered_header_path = tmp_path / "tampered_header.sovereign-capsule"
    mutated_header = bytearray(raw_capsule)
    mutated_header[45] ^= 0xAA  # Flip bits inside the 32-byte SHA-256 digest in header
    tampered_header_path.write_bytes(bytes(mutated_header))

    with pytest.raises(CapsuleIntegrityError):
        manager.import_capsule(capsule_path=tampered_header_path, passphrase=passphrase)
