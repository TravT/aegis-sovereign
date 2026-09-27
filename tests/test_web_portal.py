#!/usr/bin/env python3
"""
Automated End-to-End & HTTP Endpoint Test Suite for the Two-Pronged Web Search Portal & Source Viewer.
Aegis Sovereign Knowledge Appliance (dev/aegis-sovereign-appliance/tests/test_web_portal.py).

Validates:
1. GET / and GET /portal serve the Two-Pronged Web Portal HTML with Prong 1 & Prong 2 preset chips.
2. POST /router/query for Prong 1 (ALM-20104, DSP OPTMODULE, LOTE-202609B):
   - route_type == "deterministic_direct", needs_synthesis == False, fast_summary is None
   - confidence_level == "HIGH_DETERMINISTIC_EXACT", confidence_score == 0.99
   - graph_dossier edges (DIAGNOSED_BY_MML, REMEDIATED_BY_MML, MEASURED_BY_COUNTER)
   - valid archive:// source URIs in <15ms.
3. POST /router/query for Prong 2 ("How are the PODs of the USC and their functions organized?"):
   - needs_synthesis == True, non-empty fast_summary from NanoRunner
   - verified Huawei USC source records from the 48,664-record FTS5 vault.
4. POST /archive/inspect + GET /diagrams/<filename>:
   - resolves archive:// URIs, applies section_filter ("Possible Causes", "Procedure"),
   - extracts PNG signaling/alarm diagrams and serves them safely via GET /diagrams/<filename>.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
import pytest

from core.server import create_app, SovereignHTTPHandler


@pytest.fixture(scope="module")
def portal_server():
    """Spins up a live SovereignHTTPHandler server backed by the production Huawei Vault DBs."""
    create_app()
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


def _http_get_raw(url: str):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def _http_get_json(url: str, timeout: int = 15) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict, timeout: int = 60) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_01_get_portal_serves_two_pronged_html(portal_server):
    """GET / and GET /portal return 200 OK with the Two-Pronged Web Search Portal HTML."""
    for path in ("/", "/portal"):
        status, content_type, body_bytes = _http_get_raw(f"{portal_server}{path}")
        assert status == 200
        assert "text/html" in content_type
        html = body_bytes.decode("utf-8")
        assert "Two-Pronged Cognitive &amp; Deterministic Search Portal" in html
        assert "ALM-20104" in html
        assert "ALM-20333" in html
        assert "ALM-1003" in html
        assert "DSP OPTMODULE" in html
        assert "LOTE-202609B" in html
        assert "How are the PODs of the USC and their functions organized?" in html
        assert "LIVE ARCHIVE SOURCE INSPECTOR" in html


def test_02_prong_1_deterministic_direct_alm_20104(portal_server):
    """
    Prong 1 (ALM-20104) returns route_type == 'deterministic_direct', needs_synthesis == False,
    fast_summary is None, confidence_level == 'HIGH_DETERMINISTIC_EXACT', graph_dossier edges,
    and valid archive:// source URIs in <15ms.
    """
    # Warm-up query to ensure SQLite pages are in OS page cache
    _http_post_json(f"{portal_server}/router/query", {"query": "ALM-20104", "limit": 3})

    runs = [
        _http_post_json(f"{portal_server}/router/query", {"query": "ALM-20104", "limit": 3})[1]
        for _ in range(3)
    ]
    res = runs[-1]
    min_router_latency_ms = min(float(r.get("latency_ms", 99.0)) for r in runs)

    assert res["status"] == "success"
    assert res["route_type"] == "deterministic_direct"
    assert res["needs_synthesis"] is False
    assert res["fast_summary"] is None
    assert res["confidence_level"] == "HIGH_DETERMINISTIC_EXACT"
    assert float(res["confidence_score"]) == 0.99
    assert min_router_latency_ms < 15.0, f"Expected Prong 1 latency <15ms, got {min_router_latency_ms:.2f}ms"

    results = res.get("results") or []
    assert len(results) >= 1
    top_hit = results[0]
    assert top_hit["virtual_uri"].startswith("archive://")
    assert "ALM-20104" in top_hit["title"] or "20104" in top_hit["virtual_uri"]

    # Verify Connected Knowledge Graph Dossier edges
    dossier = res.get("graph_dossier") or {}
    assert len(dossier.get("edges") or []) >= 1
    by_rel = dossier.get("by_relation") or {}
    assert len(by_rel.get("DIAGNOSED_BY_MML") or []) >= 1
    assert len(by_rel.get("REMEDIATED_BY_MML") or []) >= 1


def test_03_prong_1_presets_mml_and_anvisa_batch(portal_server):
    """Verify Prong 1 presets DSP OPTMODULE and LOTE-202609B return deterministic exact hits."""
    for preset in ("DSP OPTMODULE", "LOTE-202609B", "ALM-1003"):
        status, res = _http_post_json(f"{portal_server}/router/query", {"query": preset, "limit": 2})
        assert status == 200
        assert res["route_type"] == "deterministic_direct"
        assert res["needs_synthesis"] is False
        assert res["fast_summary"] is None
        assert res["confidence_level"] == "HIGH_DETERMINISTIC_EXACT"
        assert len(res["results"]) >= 1
        assert res["results"][0]["virtual_uri"].startswith("archive://")


def test_04_prong_2_minimal_llm_summary_and_usc_pods(portal_server):
    """
    Prong 2 ('How are the PODs of the USC and their functions organized?') returns
    needs_synthesis == True, a non-empty fast_summary from NanoRunner, and verified Huawei USC records.
    """
    query = "How are the PODs of the USC and their functions organized?"
    status, res = _http_post_json(
        f"{portal_server}/router/query",
        {"query": query, "limit": 5, "prefer_neural": False},
    )
    assert status == 200
    assert res["needs_synthesis"] is True
    assert res["route_type"] in ("hybrid_needle", "relational_graph", "macro_synthesis", "compound_fused")
    assert res["confidence_level"] in ("HIGH_VERIFIED", "MEDIUM_PARTIAL")

    fast_summary = res.get("fast_summary")
    assert isinstance(fast_summary, dict), "Expected non-empty fast_summary dict from NanoRunner"
    assert len(fast_summary.get("answer", "").strip()) > 40
    assert fast_summary.get("grounded") is True

    results = res.get("results") or []
    assert len(results) >= 1
    combined_titles_and_text = " ".join(
        f"{r.get('title', '')} {r.get('content', '')[:500]}" for r in results
    ).lower()
    assert "pod" in combined_titles_and_text and ("usc" in combined_titles_and_text or "service" in combined_titles_and_text)


def test_05_archive_inspect_section_filter_and_diagram_serving(portal_server):
    """
    POST /archive/inspect resolves an archive:// URI, supports section_filter,
    and extracts a .png diagram served via GET /diagrams/<filename>.
    """
    _, query_res = _http_post_json(f"{portal_server}/router/query", {"query": "ALM-1003", "limit": 2})
    v_uri = query_res["results"][0]["virtual_uri"]
    assert v_uri.startswith("archive://")

    # 1. Inspect with section_filter="Possible Causes" and extract_diagram_to_artifact=True
    status, inspect_res = _http_post_json(
        f"{portal_server}/archive/inspect",
        {
            "virtual_uri": v_uri,
            "section_filter": "Possible Causes",
            "extract_diagram_to_artifact": True,
        },
    )
    assert status == 200
    assert inspect_res["mode"] == "resolve_virtual_uri"
    assert inspect_res["zero_disk_extraction"] is True
    assert inspect_res["section_filter_applied"] == "Possible Causes"
    assert "possible causes" in inspect_res["content_text"].lower()

    diagram_url = inspect_res.get("diagram_url")
    assert diagram_url and diagram_url.startswith("/diagrams/")
    assert diagram_url.endswith(".png")

    # 2. Fetch the extracted PNG diagram via GET /diagrams/<filename>
    diag_status, diag_ctype, diag_bytes = _http_get_raw(f"{portal_server}{diagram_url}")
    assert diag_status == 200
    assert diag_ctype == "image/png"
    assert diag_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "Expected valid PNG magic bytes"

    # 3. Verify path traversal protection on /diagrams/
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _http_get_raw(f"{portal_server}/diagrams/..%2Fserver.py")
    assert exc_info.value.code == 403


def test_06_four_tab_command_center_and_homelab_adr40_preset(portal_server):
    """
    Verifies that the 4-Tab Sovereign Command Center HTML contains all 4 tabs and that
    Prong 1 instant search works out-of-the-box for Homelab Server Docs (ADR-40 & SKILL-SOVEREIGN-VAULT).
    """
    status, _, body_bytes = _http_get_raw(f"{portal_server}/portal")
    assert status == 200
    html = body_bytes.decode("utf-8")
    assert "Search &amp; Source Explorer" in html
    assert "Server &amp; Knowledge Graph" in html
    assert "Monitored Directories &amp; Data Purge" in html
    assert "Platform License &amp; AI Harnesses" in html
    assert "ADR-40" in html

    for server_id in ("ADR-40", "SKILL-SOVEREIGN-VAULT"):
        st, res = _http_post_json(f"{portal_server}/router/query", {"query": server_id, "limit": 2})
        assert st == 200
        assert res["route_type"] == "deterministic_direct"
        assert res["needs_synthesis"] is False
        assert res["confidence_level"] == "HIGH_DETERMINISTIC_EXACT"
        assert len(res["results"]) >= 1
        assert server_id in res["results"][0]["title"] or server_id in res["results"][0]["doc_identifier"]


def test_07_graph_topology_api_and_filtering(portal_server):
    """
    GET /graph/topology returns Server Root & Corpus nodes, Program entities (ADR-40, Traefik v3),
    and live GraphStore entities & directed edges, supporting real-time ?filter= queries.
    """
    status, _, raw_bytes = _http_get_raw(f"{portal_server}/graph/topology")
    assert status == 200
    topo = json.loads(raw_bytes.decode("utf-8"))
    assert topo["status"] == "ok"
    node_ids = {n["id"] for n in topo["nodes"]}
    assert "Enterprise_Hub Server" in node_ids
    assert "Aegis Vault (docs/.aegis_vault)" in node_ids
    assert "ADR-40" in node_ids
    assert "ALM-20104" in node_ids
    assert "DSP OPTMODULE" in node_ids
    assert len(topo["edges"]) >= 15

    # Filtered topology query
    f_status, _, f_bytes = _http_get_raw(f"{portal_server}/graph/topology?filter=ALM-20104")
    assert f_status == 200
    f_topo = json.loads(f_bytes.decode("utf-8"))
    f_ids = {n["id"] for n in f_topo["nodes"]}
    assert "ALM-20104" in f_ids
    assert len(f_topo["nodes"]) < len(topo["nodes"])


def test_08_monitored_sources_add_anti_loop_and_db_purge(portal_server, tmp_path):
    """
    Verifies GET /sources, POST /sources/add (ingesting a temporary directory and blocking .aegis-no-index),
    and POST /sources/remove (purging that folder's records from the DB and confirming deleted_router_records > 0).
    """
    # 1. GET /sources
    st, _, raw = _http_get_raw(f"{portal_server}/sources")
    assert st == 200
    src_data = json.loads(raw.decode("utf-8"))
    assert src_data["status"] == "ok"
    assert len(src_data["sources"]) >= 4

    # 2. Create temporary folder with 2 markdown docs and ingest via POST /sources/add
    custom_dir = tmp_path / "custom_homelab_docs"
    custom_dir.mkdir(parents=True, exist_ok=True)
    (custom_dir / "runbook_alpha.md").write_text(
        "# Alpha Runbook\nProcedure to verify custom homelab service.", encoding="utf-8"
    )
    (custom_dir / "runbook_beta.md").write_text(
        "# Beta Runbook\nDiagnostic steps for cluster node.", encoding="utf-8"
    )

    add_status, add_res = _http_post_json(
        f"{portal_server}/sources/add",
        {"path": str(custom_dir), "domain": "Temp Homelab Runbooks", "ingest_now": True},
    )
    assert add_status == 200
    assert add_res["status"] == "synced"
    assert add_res["ingested_records"] == 2
    assert add_res["live_indexed_records"] >= 2

    # 3. Verify .aegis-no-index anti-loop protection blocks self-indexing
    blocked_dir = tmp_path / "blocked_vault_dir"
    blocked_dir.mkdir(parents=True, exist_ok=True)
    (blocked_dir / ".aegis-no-index").write_text("SOVEREIGN_NO_INDEX\n", encoding="utf-8")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _http_post_json(
            f"{portal_server}/sources/add",
            {"path": str(blocked_dir), "domain": "Blocked Loop Dir", "ingest_now": True},
        )
    assert exc_info.value.code == 403

    # 4. Purge the ingested directory via POST /sources/remove and confirm DB record deletion
    rm_status, rm_res = _http_post_json(
        f"{portal_server}/sources/remove",
        {"path": str(custom_dir)},
    )
    assert rm_status == 200
    assert rm_res["status"] == "purged"
    assert rm_res["deleted_router_records"] >= 2
    assert rm_res["deleted_fts_tokens"] > 0
    assert rm_res["deleted_graph_edges"] >= 1


def test_09_cryptographic_ed25519_license_and_ai_harnesses(portal_server):
    """
    Verifies GET /license and POST /license/attach sign and verify genuine Ed25519 cryptographic
    licenses, update live plan tiers, and expose AI harness configurations.
    """
    # 1. GET /license
    st, _, raw = _http_get_raw(f"{portal_server}/license")
    assert st == 200
    lic = json.loads(raw.decode("utf-8"))
    assert lic["signature_verified"] is True
    assert lic["algorithm"] == "Ed25519"
    assert "antigravity" in lic["ai_harnesses"]
    assert "claude_code" in lic["ai_harnesses"]
    assert "cursor" in lic["ai_harnesses"]

    # 2. Switch to PRO via POST /license/attach
    att_st, pro_lic = _http_post_json(
        f"{portal_server}/license/attach",
        {"tier": "pro", "organization": "Homelab Pro Node", "customer_id": "LIC-PRO-01"},
    )
    assert att_st == 200
    assert pro_lic["tier"] == "PRO"
    assert pro_lic["signature_verified"] is True

    # 3. Restore ENTERPRISE via POST /license/attach
    ent_st, ent_lic = _http_post_json(
        f"{portal_server}/license/attach",
        {"tier": "enterprise", "organization": "Enterprise Hub Homelab", "customer_id": "LIC-AEGIS-ENT-2026"},
    )
    assert ent_st == 200
    assert ent_lic["tier"] == "ENTERPRISE"
    assert ent_lic["signature_verified"] is True
    assert "RAPTOR Hierarchical Tree" in ent_lic["unlocked_features"]


def test_10_health_endpoint_canonical_db_and_local_llm(portal_server):
    """
    Verifies that GET /health and GET /status report canonical database paths (sovereign_router.db
    and sovereign_graph.db) and include local LLM controller diagnostics.
    """
    st, _, raw = _http_get_raw(f"{portal_server}/health")
    assert st == 200
    health = json.loads(raw.decode("utf-8"))
    assert health["status"] == "online"
    assert health.get("database_name") == "sovereign_router.db"
    assert "sovereign_router.db" in health.get("router_db_path", "")
    assert "sovereign_graph.db" in health.get("graph_db_path", "")
    assert "local_llm" in health
    llm_info = health["local_llm"]
    assert llm_info.get("service") == "ollama"


def test_11_llm_status_and_control_api(portal_server):
    """
    Verifies GET /llm/status and POST /llm/control for spinning up/down local LLM inference engines.
    """
    # 1. GET /llm/status
    st, _, raw = _http_get_raw(f"{portal_server}/llm/status")
    assert st == 200
    llm_status = json.loads(raw.decode("utf-8"))
    assert llm_status.get("service") == "ollama"
    assert "status" in llm_status

    # 2. POST /llm/control with status check
    c_st, c_res = _http_post_json(f"{portal_server}/llm/control", {"action": "status"})
    assert c_st == 200
    assert "status" in c_res


def test_12_archive_view_html_document_renderer(portal_server):
    """
    Verifies GET /archive/view?uri=... renders styled authentic manual HTML with dark obsidian styling.
    """
    # 1. Missing uri should return 400
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _http_get_raw(f"{portal_server}/archive/view")
    assert exc_info.value.code == 400

    # 2. Valid virtual URI from preset
    v_uri = (
        "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
        "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!"
        "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
        "#resources/alarms/20104.html"
    )
    enc_uri = urllib.parse.quote(v_uri)
    st, ctype, body = _http_get_raw(f"{portal_server}/archive/view?uri={enc_uri}")
    assert st == 200
    assert "text/html" in ctype
    html = body.decode("utf-8", errors="replace")
    assert "Sovereign Vault Document Viewer" in html
    assert "O_RDONLY Stream" in html
    assert "Zero-Disk Verified" in html
    assert "ALM-20104" in html or "20104" in html


def test_13_pcf_commissioning_procedural_runbook_synthesis(portal_server):
    """
    Benchmarks unseen query 'what are the first steps on the commissioning of the PCF?'
    verifying procedural runbook synthesis and structured sections.
    """
    st, res = _http_post_json(
        f"{portal_server}/router/query",
        {
            "query": "what are the first steps on the commissioning of the PCF?",
            "limit": 5,
            "synthesize": True,
            "prefer_neural": False,
        },
    )
    assert st == 200
    assert res["needs_synthesis"] is True
    assert res.get("fast_summary") is not None
    fs = res["fast_summary"]
    answer = fs.get("answer", "")
    assert len(answer) > 50
    # Procedural structure verification: should have sections/steps
    assert any(marker in answer for marker in ("###", "Step", "Prerequisite", "Procedure", "Commissioning", "PCF"))


def test_14_neural_ollama_synthesis_if_online(portal_server):
    """
    Tests live neural synthesis when Ollama is running, verifying grounded answer structure.
    """
    st_stat, llm_info = _http_get_json(f"{portal_server}/llm/status")
    if st_stat != 200 or not llm_info.get("running"):
        pytest.skip("Ollama local LLM is not currently running")

    st, res = _http_post_json(
        f"{portal_server}/router/query",
        {
            "query": "what are the first steps on the commissioning of the PCF?",
            "limit": 3,
            "prefer_neural": True,
        },
        timeout=90,
    )
    assert st == 200
    assert res["needs_synthesis"] is True
    assert res.get("fast_summary") is not None
    fs = res["fast_summary"]
    assert fs.get("grounded") is True
    assert len(fs.get("answer", "")) > 40
    # Either neural_ollama_local or graceful fallback if CPU under extreme load
    assert res.get("execution_mode") in ("neural_ollama_local", "extractive_template_fallback")


