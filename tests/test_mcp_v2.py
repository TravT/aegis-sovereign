"""Automated Pytest Suite for MCP Server v2 (7 Tools) & Sovereign Core HTTP Endpoints."""

from __future__ import annotations

import io
import json
import sys
import threading
import zipfile
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure appliance root is in sys.path
APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))

import core.mcp.server as mcp_server
from core.mcp.server import (
    TOOLS,
    SovereignMCPServer,
    handle_call_tool,
    handle_tool_call,
)
from core.security import ClearanceLevel
from core.server import ApplianceManager, SovereignHTTPHandler


def _create_sample_hdx(path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "alarms/0x40000001.html",
            "<html><body><h1>Alarm 0x40000001</h1><p>Optical module LOS detected on XGigabitEthernet0/0/1.</p></body></html>",
        )
        zf.writestr(
            "manuals/3gpp_ts_38_331.txt",
            "3GPP TS 38.331 RRC connection reconfiguration procedure for 5G NR.",
        )
    path.write_bytes(buf.getvalue())


@pytest.fixture
def live_appliance_server(tmp_path: Path):
    """Spins up a live SovereignHTTPHandler server on an ephemeral port with seeded records."""
    mock_searcher = MagicMock()
    mock_searcher.qdrant_target = ":memory:"
    mock_searcher.collection_name = "test_mcp_v2_collection"
    mock_searcher.search.return_value = [
        {
            "title": "ANVISA Portaria 344/98 POP-04",
            "file_path": "/docs/pop_04_psicotropicos.pdf",
            "heading": "Dispensação Lista B1",
            "score": 0.94,
            "rrf_score": 0.031,
            "text": "Protocolo de dispensação Lista B1 (Receituário Azul): retenção obrigatória e escrituração no SNGPC em até 7 dias.",
        }
    ]

    manager = ApplianceManager(searcher=mock_searcher)
    manager.router.index_document(
        doc_identifier="L2026-09B",
        title="SNGPC Lote Audit L2026-09B",
        content="LOTE: L2026-09B — Registro ANVISA MS 1.0234.5678.001-2 validado sem divergências.",
        clearance_level=ClearanceLevel.PUBLIC,
    )
    manager.graph_indexer.index_document_record(
        doc_id=101,
        title="Contrato Copel Telecom 2026",
        correspondent="Copel Telecom",
        doc_type="Contrato",
        tags=["Telecom", "SLA"],
        content="Contrato de fibra óptica corporativa com Copel Telecom no valor de R$ 1.850,00.",
        corpus="archive",
        clearance_level=ClearanceLevel.PUBLIC.value,
    )

    class BoundSovereignHandler(SovereignHTTPHandler):
        pass

    BoundSovereignHandler.manager = manager
    server = HTTPServer(("127.0.0.1", 0), BoundSovereignHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    old_url = mcp_server.APPLIANCE_URL
    mcp_server.APPLIANCE_URL = f"http://127.0.0.1:{port}"
    try:
        yield f"http://127.0.0.1:{port}", manager
    finally:
        mcp_server.APPLIANCE_URL = old_url
        server.shutdown()
        server.server_close()


def test_mcp_tools_list_exposes_all_7_tools():
    """Verify TOOLS registry and JSON-RPC tools/list expose all 7 sovereign MCP tools."""
    tool_names = [t["name"] for t in TOOLS]
    assert len(TOOLS) == 7
    expected = {
        "sovereign_optimize_context",
        "sovereign_search_vault",
        "sovereign_get_entity_dossier",
        "sovereign_node_status",
        "sovereign_route_and_analyze",
        "sovereign_inspect_archive",
        "sovereign_scan_onboarding_radar",
    }
    assert set(tool_names) == expected

    # Verify JSON-RPC stdio dispatch for initialize and tools/list
    rpc_input = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
    )
    stdin_buf = io.StringIO(rpc_input)
    stdout_buf = io.StringIO()

    orig_stdin, orig_stdout = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = stdin_buf, stdout_buf
    try:
        SovereignMCPServer().run_stdio()
    finally:
        sys.stdin, sys.stdout = orig_stdin, orig_stdout

    responses = [json.loads(line) for line in stdout_buf.getvalue().strip().splitlines()]
    assert len(responses) == 2
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "sovereign-vault"
    assert responses[1]["id"] == 2
    listed_names = {t["name"] for t in responses[1]["result"]["tools"]}
    assert listed_names == expected


def test_all_7_mcp_tools_against_live_appliance_server(live_appliance_server, tmp_path: Path):
    """Verify all 7 MCP tools execute end-to-end against SovereignHTTPHandler."""
    base_url, _ = live_appliance_server

    # 1. sovereign_optimize_context
    res_opt = handle_call_tool(
        "sovereign_optimize_context",
        {"query": "Portaria 344 Lista B1", "max_chunks": 2, "retrieval_mode": "high_precision"},
    )
    assert not res_opt.get("isError")
    opt_data = json.loads(res_opt["content"][0]["text"])
    assert "token_economics" in opt_data

    # 2. sovereign_search_vault
    res_search = handle_call_tool(
        "sovereign_search_vault",
        {"query": "SNGPC Lista B1", "limit": 3},
    )
    assert not res_search.get("isError")
    search_data = json.loads(res_search["content"][0]["text"])
    assert search_data["total"] >= 1

    # 3. sovereign_get_entity_dossier
    res_dossier = handle_call_tool(
        "sovereign_get_entity_dossier",
        {"entity_name": "Copel Telecom"},
    )
    assert not res_dossier.get("isError")
    dossier_data = json.loads(res_dossier["content"][0]["text"])
    assert "entity" in dossier_data

    # 4. sovereign_node_status
    res_status = handle_call_tool("sovereign_node_status", {})
    assert not res_status.get("isError")
    status_data = json.loads(res_status["content"][0]["text"])
    assert status_data["status"] == "online"

    # 5a. sovereign_route_and_analyze — Prong 1 deterministic_direct (<2ms)
    res_route_direct = handle_call_tool(
        "sovereign_route_and_analyze",
        {"query": "LOTE: L2026-09B", "user_clearance": "public", "synthesize": False},
    )
    assert not res_route_direct.get("isError")
    direct_data = json.loads(res_route_direct["content"][0]["text"])
    assert direct_data["route_type"] == "deterministic_direct"
    assert direct_data["execution_mode"] == "deterministic_direct_fast_path"

    # 5b. sovereign_route_and_analyze — Prong 2 analytical synthesis with fast_summary & execution_mode
    res_route_synth = handle_call_tool(
        "sovereign_route_and_analyze",
        {
            "query": "Por que a retenção e escrituração no SNGPC da Lista B1 é obrigatória e como funciona?",
            "user_clearance": "public",
            "synthesize": True,
        },
    )
    assert not res_route_synth.get("isError")
    synth_data = json.loads(res_route_synth["content"][0]["text"])
    assert synth_data["fast_summary"] is not None
    assert synth_data["fast_summary"]["execution_mode"] in (
        "extractive_template_fallback",
        "neural_ollama_local",
        "neural_onnx_local",
    )

    # 6. sovereign_inspect_archive — list TOC & resolve virtual_uri from .hdx container
    hdx_path = tmp_path / "huawei_s6730_hedex.hdx"
    _create_sample_hdx(hdx_path)

    res_archive_toc = handle_call_tool(
        "sovereign_inspect_archive",
        {"archive_path": str(hdx_path), "query": "0x40000001"},
    )
    assert not res_archive_toc.get("isError")
    toc_data = json.loads(res_archive_toc["content"][0]["text"])
    assert toc_data["zero_disk_extraction"] is True
    assert toc_data["matched_entries_count"] == 1
    v_uri = toc_data["table_of_contents"][0]["virtual_uri"]
    assert v_uri == f"archive://{hdx_path}#alarms/0x40000001.html"

    res_archive_uri = handle_call_tool(
        "sovereign_inspect_archive",
        {"virtual_uri": v_uri},
    )
    uri_data = json.loads(res_archive_uri["content"][0]["text"])
    assert uri_data["mode"] == "resolve_virtual_uri"
    assert "Optical module LOS detected" in uri_data["content_text"]

    # 7. sovereign_scan_onboarding_radar — scan domain directories
    fiscal_dir = tmp_path / "notas_fiscais_nfe"
    fiscal_dir.mkdir()
    (fiscal_dir / "danfe_2026_01.xml").write_text("<nfe>CNPJ 12.345.678/0001-90</nfe>", encoding="utf-8")
    (fiscal_dir / "fatura_icms.pdf").write_bytes(b"%PDF-1.4 fake fiscal invoice")

    res_radar = handle_call_tool(
        "sovereign_scan_onboarding_radar",
        {"root_paths": [str(tmp_path)], "max_scan_seconds": 10.0},
    )
    assert not res_radar.get("isError")
    radar_data = json.loads(res_radar["content"][0]["text"])
    assert radar_data["status"] == "completed"
    assert radar_data["total_candidates"] >= 1
    categories = {c["domain_category"] for c in radar_data["candidates"]}
    assert "fiscal_nfe" in categories or "engineering_manuals" in categories


def test_mcp_v2_in_process_fallbacks_when_server_offline(tmp_path: Path):
    """Verify sovereign_route_and_analyze, sovereign_inspect_archive, and sovereign_scan_onboarding_radar work offline via in-process fallback."""
    old_url = mcp_server.APPLIANCE_URL
    mcp_server.APPLIANCE_URL = "http://127.0.0.1:59999"  # Unreachable port
    try:
        # 1. sovereign_route_and_analyze offline fallback
        res_route = handle_tool_call(
            "sovereign_route_and_analyze",
            {"query": "3GPP TS 38.331", "user_clearance": "public"},
        )
        route_data = json.loads(res_route["content"][0]["text"])
        assert route_data["fallback_execution"] == "in_process_local"
        assert route_data["route_type"] == "deterministic_direct"
        assert "execution_mode" in route_data

        # 2. sovereign_inspect_archive offline fallback
        hdx_path = tmp_path / "offline_manual.hdx"
        _create_sample_hdx(hdx_path)
        res_arch = handle_tool_call(
            "sovereign_inspect_archive",
            {"archive_path": str(hdx_path)},
        )
        arch_data = json.loads(res_arch["content"][0]["text"])
        assert arch_data["fallback_execution"] == "in_process_local"
        assert arch_data["total_entries"] == 2
        assert arch_data["zero_disk_extraction"] is True

        # 3. sovereign_scan_onboarding_radar offline fallback
        med_dir = tmp_path / "clinica_prontuarios_laudos"
        med_dir.mkdir()
        (med_dir / "paciente_laudo_anvisa.pdf").write_bytes(b"%PDF-1.4 clinical record")
        res_scan = handle_tool_call(
            "sovereign_scan_onboarding_radar",
            {"root_paths": [str(med_dir)], "max_scan_seconds": 5.0},
        )
        scan_data = json.loads(res_scan["content"][0]["text"])
        assert scan_data["fallback_execution"] == "in_process_local"
        assert scan_data["total_candidates"] == 1
        assert scan_data["candidates"][0]["domain_category"] == "medical_clinical"
    finally:
        mcp_server.APPLIANCE_URL = old_url


def test_persistent_huawei_26_1_0_corpus_across_all_5_mcp_tools():
    """Verify live persistent Huawei 26.1.0 SQLite DBs across all 5 MCP tools for all 4 target Huawei queries."""
    assert mcp_server.DEFAULT_HUAWEI_ROUTER_DB.exists(), "sovereign_huawei_router.db must exist"
    assert mcp_server.DEFAULT_HUAWEI_GRAPH_DB.exists(), "sovereign_huawei_graph.db must exist"

    queries = [
        {
            "query": "ALM-1003 Module Fault auto-healing root alarm diagram",
            "expected_tokens": ["ALM-1003", "en-us_image_0269895191.png"],
            "expected_entity": "ALM-1003",
        },
        {
            "query": "Session Binding Function USCFD-012001 RMV BINDINFO CLR SUBDATA",
            "expected_tokens": ["BINDINFO", "SUBDATA"],
            "expected_entity": "USCFD-012001",
        },
        {
            "query": "UPCF 5G Service configuration hierarchy Package Service Policy Rule NGACTION",
            "expected_tokens": ["Package", "Policy", "Rule", "NGACTION"],
            "expected_entity": "UPCF_5G_SERVICE_CONFIG",
        },
        {
            "query": "CSP process data collection CollectAndCheck OpsAgent RunLog",
            "expected_tokens": ["CollectAndCheck", "OpsAgent"],
            "expected_entity": "CSP_26.1.0",
        },
    ]

    for qinfo in queries:
        q = qinfo["query"]

        # 1. sovereign_route_and_analyze
        res_route = handle_call_tool("sovereign_route_and_analyze", {"query": q, "user_clearance": "public"})
        assert not res_route.get("isError")
        route_data = json.loads(res_route["content"][0]["text"])
        route_blob = json.dumps(route_data)
        assert ("archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/" in route_blob or "archive:///tmp/docs_rag_gemini/" in route_blob)
        for tok in qinfo["expected_tokens"]:
            assert tok in route_blob, f"Expected '{tok}' in sovereign_route_and_analyze for query '{q}'"

        # 2. sovereign_optimize_context
        res_opt = handle_call_tool("sovereign_optimize_context", {"query": q, "top_k": 5})
        assert not res_opt.get("isError")
        opt_text = res_opt["content"][0]["text"]
        assert ("archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/" in opt_text or "archive:///tmp/docs_rag_gemini/" in opt_text)
        for tok in qinfo["expected_tokens"][:2]:
            assert tok in opt_text, f"Expected '{tok}' in sovereign_optimize_context for query '{q}'"

        # 3. sovereign_search_vault
        res_search = handle_call_tool("sovereign_search_vault", {"query": q, "limit": 5})
        assert not res_search.get("isError")
        search_data = json.loads(res_search["content"][0]["text"])
        assert search_data["total"] >= 1
        assert any(
            (r.get("virtual_uri") or r.get("file_path") or "").startswith(
                ("archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/", "archive:///tmp/docs_rag_gemini/")
            )
            for r in search_data["results"]
        )

        # 4. sovereign_get_entity_dossier
        res_dossier = handle_call_tool(
            "sovereign_get_entity_dossier",
            {"entity_name": qinfo["expected_entity"], "max_hops": 2},
        )
        assert not res_dossier.get("isError")
        dossier_data = json.loads(res_dossier["content"][0]["text"])
        assert dossier_data.get("entity") is not None
        assert len(dossier_data["neighbors"]) >= 1
        assert len(dossier_data["edges"]) >= 1

    # 5. sovereign_inspect_archive (nested archive:// stream extraction if /tmp/docs_rag_gemini is present)
    usc_zip = Path("/tmp/docs_rag_gemini/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip")
    if usc_zip.exists():
        res_inspect_hdx = handle_call_tool(
            "sovereign_inspect_archive",
            {
                "virtual_uri": (
                    "archive:///tmp/docs_rag_gemini/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip"
                    "!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
                    "#resources/alarm_cgplite/alarms/1003.html"
                ),
            },
        )
        assert not res_inspect_hdx.get("isError")
        inspect_hdx_data = json.loads(res_inspect_hdx["content"][0]["text"])
        assert "1003" in json.dumps(inspect_hdx_data)

