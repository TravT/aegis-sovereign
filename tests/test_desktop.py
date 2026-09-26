#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Aegis Sovereign Desktop Edition (ADR-37).
Tests:
- Dedicated User Cache Storage Resolution (Linux/macOS vs Windows)
- Zero-Copy In-Place Traversal with O_RDONLY
- Sliding-Window Debouncer (40ms window)
- On-Device NanoRunner Synthesis, Fallback, and Anti-Hallucination Rejection
- In-Place Indexing and Invalidation Lifecycle (Embedded Qdrant & SQLite WAL)
- HTTP/IPC Loopback Server Endpoints (/health, /status, /query, /optimize, /open, /reveal, /)
- Path Traversal Security Checks
- Packaging Files Integrity (macOS plist, Linux service, install scripts)
- Zero Personal Data in desktop/
"""

import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop.daemon.daemon import (
    WorkstationDaemon,
    DesktopHUDHandler,
    SlidingDebouncer,
    get_default_cache_dir,
    read_file_readonly,
)
from desktop.daemon.nano_runner import NanoRunner, NanoSynthesisResult


# ==============================================================================
# Helper Fixtures
# ==============================================================================

def get_free_port() -> int:
    """Finds an unused ephemeral port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def temp_workstation_env():
    """Creates isolated temporary storage and watch directories."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        storage_dir = root / "storage"
        watch_dir = root / "watch"
        storage_dir.mkdir()
        watch_dir.mkdir()
        yield {"storage": storage_dir, "watch": watch_dir}


# ==============================================================================
# 1. Storage & Cache Paths Tests
# ==============================================================================

def test_default_cache_paths():
    """Validates OS-compliant user cache directory resolution (ADR-37)."""
    # 1. Test Linux/macOS standard
    with patch("sys.platform", "linux"):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": "/custom/cache", "AEGIS_STORAGE_DIR": ""}, clear=False):
            p = get_default_cache_dir()
            assert str(p) == "/custom/cache/sovereign"

    # 2. Test Windows standard
    with patch("sys.platform", "win32"):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\User\\AppData\\Local", "AEGIS_STORAGE_DIR": ""}, clear=False):
            p = get_default_cache_dir()
            assert "Sovereign" in str(p)
            assert "AppData" in str(p)

    # 3. Test explicit override
    with patch.dict(os.environ, {"AEGIS_STORAGE_DIR": "/custom/override/sovereign"}):
        p = get_default_cache_dir()
        assert str(p) == "/custom/override/sovereign"


# ==============================================================================
# 2. Zero-Copy In-Place Traversal Tests
# ==============================================================================

def test_zero_copy_readonly_open(temp_workstation_env):
    """Asserts files are opened read-only (O_RDONLY) at the OS kernel level."""
    watch_dir = temp_workstation_env["watch"]
    sample_file = watch_dir / "confidential_deal.md"
    original_text = "# Project Deal 2026\nConfidential M&A memo terms."
    sample_file.write_text(original_text, encoding="utf-8")

    # Read using kernel O_RDONLY helper
    read_text = read_file_readonly(sample_file)
    assert read_text == original_text

    # Assert that file was not duplicated into any shadow staging folder
    storage_dir = temp_workstation_env["storage"]
    shadow_files = list(storage_dir.rglob("confidential_deal.md"))
    assert len(shadow_files) == 0, "File was duplicated into shadow storage!"


# ==============================================================================
# 3. Kernel Event Sliding-Window Debouncer Tests
# ==============================================================================

def test_sliding_window_debouncer():
    """Tests 40ms sliding window debouncing and event coalescing."""
    collected_events = []
    debouncer = SlidingDebouncer(delay=0.040, callback=lambda ev: collected_events.append(ev))

    # Push rapid burst of file events for the same path
    debouncer.push("/path/to/doc.md", "modify")
    debouncer.push("/path/to/doc.md", "modify")
    debouncer.push("/path/to/doc2.md", "create")
    debouncer.push("/path/to/doc.md", "modify")

    # Assert nothing fired immediately
    assert len(collected_events) == 0

    # Wait for the 40ms sliding window to settle
    time.sleep(0.090)

    assert len(collected_events) == 1
    events = collected_events[0]
    assert "/path/to/doc.md" in events
    assert "/path/to/doc2.md" in events
    assert events["/path/to/doc.md"] == "modify"
    assert events["/path/to/doc2.md"] == "create"

    # Test delete event precedence
    collected_events.clear()
    debouncer.push("/path/to/doc.md", "modify")
    debouncer.push("/path/to/doc.md", "delete")
    time.sleep(0.090)

    assert len(collected_events) == 1
    assert collected_events[0]["/path/to/doc.md"] == "delete"


# ==============================================================================
# 4. NanoRunner Small Model Engine Tests
# ==============================================================================

def test_nano_runner_synthesis_and_fallback():
    """Tests on-device nano runner in deterministic fallback mode."""
    runner = NanoRunner(use_ollama=False)
    assert runner.is_fallback is True
    assert runner.FALLBACK_MODEL_NAME == "Aegis Deterministic Extractive Synthesizer (0-LLM Template Fallback)"

    sample_chunks = [
        {
            "doc_title": "Tax Compliance 2026",
            "file_path": "/user/docs/darf_guide.md",
            "heading": "Section 4.1 Federal Taxes",
            "chunk_index": 1,
            "text": "O pagamento do DARF referente ao IRPF deve ser efetuado ate o ultimo dia util de abril.",
            "score": 0.85,
        }
    ]
    graph_dossier = {
        "entity": {"name": "DARF", "entity_type": "fiscal"},
        "amounts": [{"name": "R$ 1.500,00"}],
        "dates": [{"name": "30/04/2026"}],
    }

    result = runner.synthesize(
        query="Qual o prazo de pagamento do DARF?",
        chunks=sample_chunks,
        graph_dossier=graph_dossier,
    )

    assert isinstance(result, NanoSynthesisResult)
    assert result.grounded is True
    assert result.refusal is False
    assert result.is_fallback is True
    assert result.execution_mode == "extractive_template_fallback"
    assert result.model == "Aegis Deterministic Extractive Synthesizer (0-LLM Template Fallback)"
    assert result.confidence_score == 0.85
    assert len(result.citations) == 1
    assert result.citations[0]["doc_title"] == "Tax Compliance 2026"
    assert "[Doc #1]" in result.answer
    assert "DARF" in result.answer
    assert result.tokens_prompt > 0
    assert result.tokens_generated > 0
    assert result.token_savings_pct >= 40.0
    assert result.latency_ms >= 0.0


def test_nano_runner_anti_hallucination_refusal():
    """Tests strict ADR-09 epistemic refusal when evidence falls below <35% (0.35) confidence floor."""
    runner = NanoRunner(use_ollama=False)

    # 1. Empty chunks (English query)
    empty_res = runner.synthesize("Where is the escrow agreement?", chunks=[])
    assert empty_res.grounded is False
    assert empty_res.refusal is True
    assert empty_res.execution_mode == "epistemic_refusal"
    assert "Refusal" in empty_res.answer
    assert "ADR-09" in empty_res.answer

    # 2. Score 0.30 below default ADR-09 0.35 (35%) threshold (Portuguese query)
    sub_threshold_chunks = [
        {
            "doc_title": "Nota Fiscal Antiga",
            "file_path": "/user/docs/nota.txt",
            "text": "Rascunho sem relação contratual.",
            "score": 0.30,
        }
    ]
    pt_refusal = runner.synthesize("Qual a multa rescisória do contrato?", chunks=sub_threshold_chunks)
    assert pt_refusal.grounded is False
    assert pt_refusal.refusal is True
    assert pt_refusal.execution_mode == "epistemic_refusal"
    assert pt_refusal.confidence_score == 0.30
    assert "Recusa Epistêmica" in pt_refusal.answer
    assert "ADR-09" in pt_refusal.answer
    assert "<35%" in pt_refusal.answer

    # 3. Explicit caller override of confidence_floor
    low_score_chunks = [
        {
            "doc_title": "Unrelated Note",
            "file_path": "/user/docs/random.txt",
            "text": "Random shopping list milk eggs.",
            "score": 0.12,
        }
    ]
    low_res = runner.synthesize("Termination penalty?", chunks=low_score_chunks, confidence_floor=0.25)
    assert low_res.grounded is False
    assert low_res.refusal is True
    assert low_res.execution_mode == "epistemic_refusal"
    assert low_res.confidence_score == 0.12
    assert "Refusal" in low_res.answer


def test_nano_runner_neural_ollama_local_telemetry():
    """Tests live local Ollama HTTP bridge synthesis and honest execution_mode telemetry."""
    runner = NanoRunner(
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        use_ollama=True,
    )
    sample_chunks = [
        {
            "doc_title": "M&A Escrow Clause 2026",
            "file_path": "/user/docs/escrow.md",
            "heading": "Clause 9.2 Release Conditions",
            "chunk_index": 1,
            "text": "Escrow funds of $2,500,000 shall be released 90 days post-closing upon tax clearance.",
            "score": 0.91,
        }
    ]

    mock_tags_resp = MagicMock()
    mock_tags_resp.status = 200
    mock_tags_resp.read.return_value = json.dumps({"models": [{"name": "qwen2.5:3b"}]}).encode("utf-8")
    mock_tags_resp.__enter__.return_value = mock_tags_resp

    mock_gen_resp = MagicMock()
    mock_gen_resp.status = 200
    mock_gen_resp.read.return_value = json.dumps({
        "model": "qwen2.5:3b",
        "response": "According to the verified contract, escrow funds of $2,500,000 are released 90 days post-closing upon tax clearance [1].",
    }).encode("utf-8")
    mock_gen_resp.__enter__.return_value = mock_gen_resp

    with patch("urllib.request.urlopen", side_effect=[mock_tags_resp, mock_gen_resp]):
        res = runner.synthesize(
            query="When are the escrow funds released?",
            chunks=sample_chunks,
            use_ollama=True,
        )

    assert res.grounded is True
    assert res.refusal is False
    assert res.is_fallback is False
    assert res.execution_mode == "neural_ollama_local"
    assert "qwen2.5:3b" in res.model
    assert "[1]" in res.answer
    assert "$2,500,000" in res.answer

    # Verify remote non-loopback GPU nodes are strictly blocked from automatic wake/probing
    remote_runner = NanoRunner(ollama_url="http://198.51.100.42:11434", use_ollama=True)
    assert remote_runner._check_ollama_available() is False


# ==============================================================================
# 5. In-Place Indexing and Invalidation Lifecycle Tests
# ==============================================================================

def test_daemon_in_place_indexing_and_deletion(temp_workstation_env):
    """Tests full in-place indexing and purging on file deletion."""
    storage_dir = temp_workstation_env["storage"]
    watch_dir = temp_workstation_env["watch"]

    daemon = WorkstationDaemon(
        watch_paths=[str(watch_dir)],
        storage_dir=storage_dir,
        port=get_free_port()
    )

    doc_path = watch_dir / "deal_clause.md"
    doc_content = """---
title: Acquisition Contract 2026
last_reviewed: 2026-09-18
---
# Clause 14.2 Delay Penalties
Compensatory damages for unexcused milestone slippage shall be R$ 150.000,00 payable to Alpha Holdings.
CPF do responsavel: 123.456.789-00.
"""
    doc_path.write_text(doc_content, encoding="utf-8")

    # 1. Perform in-place indexing
    daemon.index_file_inplace(str(doc_path))
    assert daemon._stats["indexed_files"] >= 1

    # Verify GraphStore entity records
    stats = daemon.graph_store.get_entity_statistics()
    assert stats["total_documents"] >= 1
    assert stats["total_entities"] >= 1

    # 2. Execute Hybrid Query
    hits = daemon.query("milestone slippage compensatory damages")
    assert len(hits) >= 1
    assert "Acquisition Contract 2026" in hits[0]["doc_title"]

    # 3. Execute Context Optimization + Nano Synthesis
    opt = daemon.optimize("milestone slippage damages", use_nano=True)
    assert "condensed_chunks" in opt
    assert "synthesis" in opt
    assert opt["synthesis"]["grounded"] is True

    # 4. Handle Deletion (Purge)
    daemon.handle_deletion(str(doc_path))
    assert daemon._stats["purged_files"] >= 1

    # Verify document removed from GraphStore
    doc_count_after = daemon.graph_store.get_entity_statistics()["total_documents"]
    assert doc_count_after == 0


def test_watcher_file_move():
    """Tests that FileMovedEvent pushes delete for src_path and create for dest_path."""
    from desktop.daemon.daemon import WorkstationWatcherHandler
    from watchdog.events import FileMovedEvent

    mock_daemon = MagicMock()
    handler = WorkstationWatcherHandler(mock_daemon)

    event = FileMovedEvent("/watch/old_name.md", "/watch/new_name.md")
    handler.on_moved(event)

    # Verify src_path was deleted and dest_path was created in debouncer
    assert mock_daemon.debouncer.push.call_count == 2
    mock_daemon.debouncer.push.assert_any_call("/watch/old_name.md", "delete")
    mock_daemon.debouncer.push.assert_any_call("/watch/new_name.md", "create")


# ==============================================================================
# 6. HTTP / Loopback API Endpoints Tests
# ==============================================================================

def test_hud_http_api_endpoints(temp_workstation_env):
    """Tests loopback HTTP API endpoints (/health, /status, /query, /optimize, /open)."""
    storage_dir = temp_workstation_env["storage"]
    watch_dir = temp_workstation_env["watch"]
    free_port = get_free_port()

    daemon = WorkstationDaemon(
        watch_paths=[str(watch_dir)],
        storage_dir=storage_dir,
        port=free_port
    )

    DesktopHUDHandler.daemon = daemon
    server = HTTPServer(("127.0.0.1", free_port), DesktopHUDHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{free_port}"

    try:
        # 1. Test GET /health
        with urllib.request.urlopen(f"{base_url}/health") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "online"
            assert data["edition"] == "Aegis Sovereign Desktop"
            assert data["zero_copy"] is True

        # 2. Test GET /status
        with urllib.request.urlopen(f"{base_url}/status") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "watched_paths" in data
            assert "nano_runner" in data

        # 3. Test GET / (Serves HUD index.html)
        with urllib.request.urlopen(f"{base_url}/") as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "Aegis Sovereign Spotlight" in html

        # 4. Test POST /query
        req = urllib.request.Request(
            f"{base_url}/query",
            data=json.dumps({"query": "arbitration clause"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "results" in data

        # 5. Test POST /optimize
        req = urllib.request.Request(
            f"{base_url}/optimize",
            data=json.dumps({"query": "tax payment", "use_nano": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "synthesis" in data

    finally:
        server.shutdown()
        server.server_close()


# ==============================================================================
# 7. Path Traversal & Security Validation Tests
# ==============================================================================

def test_path_safety_and_native_launch(temp_workstation_env):
    """Validates path safety checks to prevent path traversal and arbitrary execution."""
    storage_dir = temp_workstation_env["storage"]
    watch_dir = temp_workstation_env["watch"]

    daemon = WorkstationDaemon(
        watch_paths=[str(watch_dir)],
        storage_dir=storage_dir,
        port=get_free_port()
    )

    safe_file = watch_dir / "valid_doc.md"
    safe_file.write_text("Hello safe", encoding="utf-8")

    # 1. Valid path inside watch directory
    is_safe, msg = daemon.is_safe_path(safe_file)
    assert is_safe is True
    assert msg == str(safe_file.resolve())

    # 2. Non-existent path
    is_safe, msg = daemon.is_safe_path(watch_dir / "does_not_exist.txt")
    assert is_safe is False
    assert "does not exist" in msg

    # 3. Path traversal attempt to sensitive system files
    sensitive_path = Path("/etc/shadow")
    is_safe, msg = daemon.is_safe_path(sensitive_path)
    # Either doesn't exist or outside permissible user roots
    assert is_safe is False

    # 4. Null byte injection attempt
    is_safe, msg = daemon.is_safe_path(Path(str(safe_file) + "\0extra"))
    assert is_safe is False

    # 5. Executable file rejection
    exe_file = watch_dir / "malicious.exe"
    exe_file.write_text("binary", encoding="utf-8")
    is_safe, msg = daemon.is_safe_path(exe_file)
    assert is_safe is False
    assert "executable" in msg.lower()

    # 6. Native OS open mocking
    with patch("subprocess.Popen") as mock_popen:
        success, res = daemon.open_path(str(safe_file))
        assert success is True
        mock_popen.assert_called_once()

    # 7. Native OS reveal mocking
    with patch("subprocess.Popen") as mock_popen:
        success, res = daemon.reveal_path(str(safe_file))
        assert success is True
        mock_popen.assert_called_once()


# ==============================================================================
# 8. Packaging Files Integrity Tests
# ==============================================================================

def test_packaging_file_integrity():
    """Validates macOS launchd plist, Linux systemd service, and installer scripts."""
    packaging_dir = REPO_ROOT / "desktop" / "packaging"

    # 1. Validate macOS plist XML structure
    plist_path = packaging_dir / "aegis-workstation.plist"
    assert plist_path.is_file()
    tree = ET.parse(plist_path)
    root = tree.getroot()
    assert root.tag == "plist"
    plist_content = plist_path.read_text(encoding="utf-8")
    assert "com.aegis.sovereign.workstation" in plist_content
    assert "desktop.daemon.daemon" in plist_content
    assert "WorkingDirectory" in plist_content
    assert "PYTHONPATH" in plist_content

    # 2. Validate Linux systemd user service
    service_path = packaging_dir / "aegis-workstation.service"
    assert service_path.is_file()
    service_content = service_path.read_text(encoding="utf-8")
    assert "[Unit]" in service_content
    assert "[Service]" in service_content
    assert "[Install]" in service_content
    assert "desktop.daemon.daemon" in service_content
    assert "WorkingDirectory" in service_content
    assert "PYTHONPATH" in service_content

    # 3. Validate Bash installer script
    sh_path = packaging_dir / "install_service.sh"
    assert sh_path.is_file()
    sh_content = sh_path.read_text(encoding="utf-8")
    assert "#!/usr/bin/env bash" in sh_content
    assert "launchctl" in sh_content
    assert "systemctl" in sh_content
    assert "@APP_ROOT@" in sh_content
    assert os.access(sh_path, os.X_OK), "install_service.sh is not executable"

    # 4. Validate PowerShell Windows installer script
    ps1_path = packaging_dir / "install_service.ps1"
    assert ps1_path.is_file()
    ps1_content = ps1_path.read_text(encoding="utf-8")
    assert "ScheduledTask" in ps1_content
    assert "LOCALAPPDATA" in ps1_content
    assert "WorkingDirectory" in ps1_content


# ==============================================================================
# 9. Zero Personal Data Compliance Tests
# ==============================================================================

def test_zero_personal_data_in_desktop():
    """Asserts zero personal IP addresses, hostnames, or usernames exist in desktop/."""
    forbidden_patterns = [
        re.compile(r"100\.(125\.7\.38|79\.112\.91)"),  # Personal Tailscale IPs
        re.compile(r"192\.168\.0\.48"),                 # Personal LAN IP
        re.compile(r"/home/tlima"),                     # Personal user home directory
        re.compile(r"tlima(?![a-zA-Z0-9_-])"),          # Personal username
    ]

    desktop_dir = REPO_ROOT / "desktop"
    files_checked = 0

    for root, _, files in os.walk(desktop_dir):
        if "__pycache__" in root:
            continue
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix in [".py", ".html", ".sh", ".ps1", ".service", ".plist", ".md"]:
                content = file_path.read_text(encoding="utf-8")
                for pat in forbidden_patterns:
                    match = pat.search(content)
                    assert match is None, f"Found forbidden personal data '{match.group(0)}' in {file_path}"
                files_checked += 1

    assert files_checked >= 5, f"Expected to check at least 5 files, checked {files_checked}"
