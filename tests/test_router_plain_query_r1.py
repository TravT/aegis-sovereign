#!/usr/bin/env python3
"""
Test Finding R1: Plain-language queries (POST /router/query) return in <2s.
Verifies that natural language questions without explicit prefer_neural=True
default to deterministic extractive synthesis rather than hanging on slow/standby LLMs.
"""

import time
import pytest
from core.server.app import create_app
from core.security import ClearanceLevel


@pytest.fixture
def test_app():
    """Initializes in-memory appliance manager for testing."""
    app = create_app(router_db_path=":memory:")
    # Seed sample documentation record for diameter link query
    app.router.index_document(
        doc_identifier="USC-DIAMETER-01",
        title="USC 26.1.0: Diameter Link Peer Timeout Recovery",
        content="When peer timeout occurs on Diameter link, execute LST DMLNK to verify status. "
        "To restore the link: 1. MOD DMLNK: LNKID=1, SW=START; 2. Verify SCTP association with DSP SCTPLNK.",
        clearance_level=ClearanceLevel.PUBLIC,
        metadata={"virtual_uri": "archive://manuals/usc_diameter.html", "domain": "telecom_vendor"},
    )
    yield app
    app.router.close()


def test_r1_plain_language_query_returns_under_two_seconds(test_app):
    """
    R1 Requirement: Plain-language query POST /router/query without prefer_neural
    must return in <2.0s with grounded extractive synthesis.
    """
    query = "how to restore diameter link after peer timeout"
    t0 = time.perf_counter()
    res = test_app.route_and_execute(
        query=query,
        user_clearance="restricted",
        limit=5,
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 2.0, f"Query took {elapsed:.2f}s, exceeding 2.0s threshold!"
    assert res["status"] == "success"
    assert res["needs_synthesis"] is True
    assert res.get("fast_summary") is not None
    fs = res["fast_summary"]
    assert fs.get("grounded") is True
    assert fs.get("execution_mode") == "extractive_template_fallback"
    assert len(fs.get("answer", "")) > 30
    assert "Diameter" in fs.get("answer", "") or "LST DMLNK" in fs.get("answer", "")


def test_r1_prefer_neural_honors_timeout_and_falls_back(test_app, monkeypatch):
    """
    R1 Requirement: If prefer_neural=True is requested and the LLM endpoint is slow/hung,
    it must honor SOVEREIGN_LLM_TIMEOUT and cleanly fall back to extractive template synthesis.
    """
    monkeypatch.setenv("SOVEREIGN_LLM_TIMEOUT", "0.5")
    # Point llama_cpp to a non-responsive or slow host to verify bounded timeout
    test_app.nano_runner.llama_cpp_url = "http://127.0.0.1:19999"
    test_app.nano_runner.use_ollama = True

    query = "how to restore diameter link after peer timeout"
    t0 = time.perf_counter()
    res = test_app.route_and_execute(
        query=query,
        user_clearance="restricted",
        limit=5,
        prefer_neural=True,
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 2.5, f"Query took {elapsed:.2f}s with timeout enabled!"
    assert res["status"] == "success"
    assert res.get("fast_summary") is not None
    # Graceful fallback to extractive synthesis
    assert res["execution_mode"] in ("extractive_template_fallback", "epistemic_refusal")
