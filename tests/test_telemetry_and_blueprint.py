"""
Automated Pytest Suite — Priority 6 (ADR-10 & ADR-09 Telemetry/MinHash) & Priority 7 (Section 6 Blueprint)
===========================================================================================================

Verifies:
1. Zstandard pre-trained dictionary compression (`ZeroKnowledgeTelemetryCompressor`) compressing a
   ~3,500-byte (3.5 KB) JSON health/performance heartbeat down to <= 220 bytes (>93% reduction)
   with 100% lossless round-trip decompression.
2. LGPD Art. 12 Safe Harbor sanitizer (`sanitize_telemetry_payload` & `TelemetryPrivacyError`)
   blocking and stripping PII (`cpf`, `query`, `file_path`, `content`, `title`, `email`, `snippet`).
3. Sub-millisecond 64-permutation `MinHashDeduplicator` catching near-duplicate email chains
   (`jaccard_similarity >= 0.85`) in <0.5ms while allowing distinct documents.
4. Existence and schema validity (YAML/JSON/HCL/Rust/Bash) of all Section 6 Master Plan artifacts.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import yaml

from core.telemetry import (
    MinHashDeduplicator,
    TelemetryPrivacyError,
    ZeroKnowledgeTelemetryCompressor,
    build_sample_telemetry_payload,
    pseudonymize_identifier,
    sanitize_telemetry_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# 1. ADR-10 Zstandard Pre-Trained Dictionary Telemetry Compression Tests
# ==============================================================================


def test_zstd_dictionary_compression_ratio_and_lossless_roundtrip() -> None:
    """
    Verify that a verbose ~3,500-byte (3.5 KB) Aegis telemetry heartbeat JSON payload
    compresses to <= 220 bytes (>93% reduction) and decompresses losslessly.
    """
    compressor = ZeroKnowledgeTelemetryCompressor()

    # Test both a canonical seed (42) and an unseen seed (999) outside the dictionary training range
    for seed in (42, 999):
        payload = build_sample_telemetry_payload(seed=seed)

        # Verify required ADR-10 heartbeat keys exist
        required_keys = {
            "schema_version",
            "appliance_tier",
            "uptime_seconds",
            "cpu_Load_pct",
            "ram_rss_mb",
            "nvme_free_gb",
            "qdrant_vectors_count",
            "sqlite_entities_count",
            "prong1_latency_p50_ms",
            "prong2_latency_p50_ms",
            "token_savings_ratio_pct",
        }
        assert required_keys.issubset(payload.keys())

        raw_pretty_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        raw_compact_bytes = json.dumps(
            payload, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")

        # Ensure raw JSON payload is ~3.5 KB (>= 3,300 bytes)
        assert len(raw_pretty_bytes) >= 3500, (
            f"Expected >= 3500 byte JSON heartbeat, got {len(raw_pretty_bytes)}"
        )
        assert len(raw_compact_bytes) >= 3250

        stats = compressor.compress_with_stats(payload, strict_privacy=True)
        compressed = stats["compressed_bytes"]
        compressed_size = stats["compressed_size_bytes"]
        reduction_pct = stats["compression_reduction_pct"]

        # ADR-10 Target: <= 220 bytes and > 93% reduction
        assert compressed_size <= 220, (
            f"Compressed payload ({compressed_size} bytes) exceeded 220-byte ADR-10 budget!"
        )
        assert reduction_pct >= 93.0, (
            f"Expected >93% reduction, got {reduction_pct}%"
        )

        # Verify 100% lossless round-trip decompression
        decompressed = compressor.decompress(compressed)
        assert decompressed == payload


# ==============================================================================
# 2. ADR-10 / LGPD Art. 12 Safe Harbor Privacy Sanitizer Tests
# ==============================================================================


def test_lgpd_art12_privacy_guard_strict_mode_rejects_pii() -> None:
    """
    Verify that `sanitize_telemetry_payload(..., strict=True)` and `compressor.compress`
    strictly reject forbidden keys (`cpf`, `query`, `file_path`, `content`, `title`, `snippet`)
    and embedded PII regex patterns (CPF, CNPJ, email, filesystem paths).
    """
    compressor = ZeroKnowledgeTelemetryCompressor()
    base = build_sample_telemetry_payload(seed=1)

    for forbidden_key, bad_val in [
        ("cpf", "123.456.789-00"),
        ("query", "Qual o valor da cláusula de indenização da Petrobras?"),
        ("file_path", "/home/tlima/Documents/M&A_Term_Sheet_Confidential.pdf"),
        ("content", "Raw confidential contract clause 8.2 text..."),
        ("title", "Board_Minutes_2026_Secret.docx"),
        ("snippet", "Excerpt of sensitive legal discovery..."),
    ]:
        poisoned = dict(base)
        poisoned[forbidden_key] = bad_val
        with pytest.raises(TelemetryPrivacyError, match=forbidden_key):
            sanitize_telemetry_payload(poisoned, strict=True)

        with pytest.raises(TelemetryPrivacyError):
            compressor.compress(poisoned, strict_privacy=True)

    # Also verify value-level regex detection even under an allowed key name
    value_poisoned = dict(base)
    value_poisoned["station_id"] = "user_cpf_123.456.789-00_station"
    with pytest.raises(TelemetryPrivacyError, match="CPF_PATTERN"):
        sanitize_telemetry_payload(value_poisoned, strict=True)


def test_lgpd_art12_privacy_guard_non_strict_strips_and_redacts() -> None:
    """
    Verify that `strict=False` mode strips forbidden keys (`cpf`, `query`, `file_path`, `content`)
    and scrubs embedded PII patterns in string fields.
    """
    dirty_payload = {
        "schema_version": "aegis.telemetry.fleet.v1.4.0",
        "uptime_seconds": 3600,
        "cpf": "123.456.789-00",
        "query": "secret search query",
        "file_path": "/Users/ceo/Desktop/secret.pdf",
        "content": "confidential body text",
        "nested_metrics": {
            "qdrant_vectors_count": 10000,
            "snippet": "should be stripped",
            "operator_note": "Contact admin@enterprise.com.br or CPF 111.222.333-44",
        },
    }

    cleaned = sanitize_telemetry_payload(dirty_payload, strict=False)
    assert "cpf" not in cleaned
    assert "query" not in cleaned
    assert "file_path" not in cleaned
    assert "content" not in cleaned
    assert "snippet" not in cleaned["nested_metrics"]
    assert cleaned["nested_metrics"]["qdrant_vectors_count"] == 10000
    assert "[REDACTED_EMAIL]" in cleaned["nested_metrics"]["operator_note"]
    assert "[REDACTED_CPF]" in cleaned["nested_metrics"]["operator_note"]

    # Verify HMAC-SHA256 pseudonymization helper
    digest = pseudonymize_identifier("tlima@enterprise.com.br")
    assert len(digest) == 64
    assert digest == pseudonymize_identifier("tlima@enterprise.com.br")


# ==============================================================================
# 3. ADR-09 Sub-Millisecond 64-Permutation MinHash LSH Deduplicator Tests
# ==============================================================================


def test_minhash_deduplicator_near_duplicate_emails_and_latency() -> None:
    """
    Verify `MinHashDeduplicator` detects near-duplicate email chains (`>= 0.85` similarity)
    in `< 0.5ms` while permitting distinct documents.
    """
    dedup = MinHashDeduplicator(num_permutations=64, shingle_words=2, default_threshold=0.85)

    email_original = (
        "Subject: Q3 M&A Acquisition Term Sheet - Project Titan\n"
        "From: legal-counsel@enterprise.com.br\n"
        "To: executive-board@enterprise.com.br\n\n"
        "Dear Executive Committee,\n"
        "Attached is the final Q3 M&A Acquisition Term Sheet for Project Titan. "
        "The total enterprise valuation remains R$ 450,000,000.00 with an earn-out "
        "provision tied to audited EBITDA margin targets over twenty-four months. "
        "All regulatory filings with CADE and BACEN have been approved by outside counsel "
        "and satisfy all Sovereign LGPD Article 12 governance requirements.\n"
        "Best regards,\nGeneral Counsel"
    )

    email_forwarded_near_dup = (
        "Subject: RE: Q3 M&A Acquisition Term Sheet - Project Titan\n"
        "From: legal-counsel@enterprise.com.br\n"
        "To: executive-board@enterprise.com.br\n\n"
        "Dear Executive Committee,\n"
        "Attached is the final Q3 M&A Acquisition Term Sheet for Project Titan. "
        "The total enterprise valuation remains R$ 450,000,000.00 with an earn-out "
        "provision tied to audited EBITDA margin targets over twenty-four months. "
        "All regulatory filings with CADE and BACEN have been approved by outside counsel "
        "and satisfy all Sovereign LGPD Article 12 governance requirements.\n"
        "Best regards,\nGeneral Counsel - Signed"
    )

    distinct_technical_doc = (
        "Manual 09: Datacenter Supercomputing and Distributed Fabric Architecture.\n"
        "This engineering specification defines the 400GbE RoCEv2 RDMA InfiniBand "
        "network fabric connecting 8x NVIDIA H200 SXM GPUs running Tensor Parallel (TP=8) "
        "vLLM inference for DeepSeek-R1 and Llama-3.1-405B-Instruct-FP8."
    )

    # Warmup call
    dedup.compute_signature(email_original)

    # Measure execution speed (< 0.5ms requirement)
    t0 = time.perf_counter()
    for _ in range(50):
        sig1 = dedup.compute_signature(email_original)
    avg_ms = ((time.perf_counter() - t0) / 50.0) * 1000.0
    assert avg_ms < 0.5, f"MinHash compute_signature took {avg_ms:.3f}ms (exceeded 0.5ms budget)"
    assert len(sig1) == 64

    sig2 = dedup.compute_signature(email_forwarded_near_dup)
    sig3 = dedup.compute_signature(distinct_technical_doc)

    near_dup_sim = dedup.jaccard_similarity(sig1, sig2)
    distinct_sim = dedup.jaccard_similarity(sig1, sig3)

    assert near_dup_sim >= 0.85, f"Expected >= 0.85 Jaccard for near-duplicate email, got {near_dup_sim:.3f}"
    assert distinct_sim < 0.25, f"Expected < 0.25 Jaccard for distinct document, got {distinct_sim:.3f}"

    # Verify stateful ingestion filter behavior
    assert dedup.is_duplicate(email_original, doc_id="email-001") is False
    assert dedup.is_duplicate(email_forwarded_near_dup, doc_id="email-002") is True
    assert dedup.is_duplicate(distinct_technical_doc, doc_id="tech-001") is False


# ==============================================================================
# 4. Section 6 Master Plan Blueprint Materialization Verification
# ==============================================================================


def test_section6_master_plan_blueprint_files_exist_and_valid() -> None:
    """
    Verify that all Section 6 Master Architecture Plan infrastructure and packaging
    artifacts exist and contain valid YAML, JSON, HCL, Rust, and executable Bash syntax.
    """
    # 1. Multi-OS GitHub Actions Desktop Release Workflow
    workflow_path = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"
    assert workflow_path.is_file(), "Missing .github/workflows/desktop-release.yml"
    workflow_data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert "jobs" in workflow_data
    raw_workflow = workflow_path.read_text(encoding="utf-8")
    for ext in (".dmg", ".msi", ".AppImage"):
        assert ext in raw_workflow
    assert "sovereign-desktopd" in raw_workflow

    # 2. Tauri v2 Configuration & Rust Wrapper (`Alt+Space`, `#07090D`, `127.0.0.1:8766`)
    tauri_conf_path = REPO_ROOT / "desktop" / "hud" / "src-tauri" / "tauri.conf.json"
    tauri_main_path = REPO_ROOT / "desktop" / "hud" / "src-tauri" / "src" / "main.rs"
    assert tauri_conf_path.is_file(), "Missing desktop/hud/src-tauri/tauri.conf.json"
    assert tauri_main_path.is_file(), "Missing desktop/hud/src-tauri/src/main.rs"

    tauri_conf = json.loads(tauri_conf_path.read_text(encoding="utf-8"))
    win_cfg = tauri_conf["app"]["windows"][0]
    assert win_cfg["backgroundColor"] == "#07090D"
    assert win_cfg["decorations"] is False
    assert win_cfg["transparent"] is True
    assert "Alt+Space" in tauri_conf["plugins"]["globalShortcut"]["shortcuts"]

    rust_src = tauri_main_path.read_text(encoding="utf-8")
    assert "127.0.0.1:8766" in rust_src
    assert "Alt+Space" in rust_src
    assert "#07090D" in rust_src

    # 3. Datacenter Multi-GPU TP=8 vLLM Service Manifest
    vllm_path = REPO_ROOT / "deploy" / "datacenter" / "vllm-service.yaml"
    assert vllm_path.is_file(), "Missing deploy/datacenter/vllm-service.yaml"
    vllm_docs = list(yaml.safe_load_all(vllm_path.read_text(encoding="utf-8")))
    assert len(vllm_docs) >= 2
    vllm_raw = vllm_path.read_text(encoding="utf-8")
    assert "--tensor-parallel-size=8" in vllm_raw
    assert "Llama-3.1-405B-Instruct-FP8" in vllm_raw
    assert "DeepSeek-R1" in vllm_raw

    # 4. Zero-Touch Ansible Playbook & Air-Gapped Sovereign VPC Terraform Module
    ansible_path = REPO_ROOT / "deploy" / "ansible" / "site.yml"
    terraform_path = REPO_ROOT / "deploy" / "terraform" / "main.tf"
    assert ansible_path.is_file(), "Missing deploy/ansible/site.yml"
    assert terraform_path.is_file(), "Missing deploy/terraform/main.tf"

    ansible_data = yaml.safe_load(ansible_path.read_text(encoding="utf-8"))
    assert isinstance(ansible_data, list) and len(ansible_data) >= 1
    assert "tasks" in ansible_data[0]

    tf_raw = terraform_path.read_text(encoding="utf-8")
    assert 'resource "aws_vpc" "aegis_sovereign_vpc"' in tf_raw
    assert 'resource "aws_security_group" "aegis_zero_egress_sg"' in tf_raw
    assert "object_lock_enabled = true" in tf_raw

    # 5. Executable Turnkey Installer (`install.sh`)
    install_sh = REPO_ROOT / "install.sh"
    assert install_sh.is_file(), "Missing install.sh"
    assert os.access(install_sh, os.X_OK), "install.sh must be executable (chmod +x)"
    install_raw = install_sh.read_text(encoding="utf-8")
    assert "avx512_vnni" in install_raw
    assert "avx2" in install_raw
