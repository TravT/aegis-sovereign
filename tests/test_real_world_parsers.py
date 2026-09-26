"""Automated Pytest Suite for Real-World Enterprise Format Parsers & 7-Tool MCP Benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure appliance root is in sys.path
APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))

from benchmarks.benchmark_mcp_7_tools import (
    SAMPLE_CLINICAL_CSV,
    SAMPLE_NFE_V400_XML,
    SAMPLE_NOC_MBOX,
)
from core.formats.real_world_parsers import (
    MboxEmailParser,
    NfeXmlParser,
    TabularCsvParser,
    XmlSecurityError,
)
from core.graph.store import GraphStore
from core.router.query_router import QueryRouteType, SovereignQueryRouter
from core.security import ClearanceLevel


def test_nfe_xml_parser_extracts_rastro_med_and_indexes_graph():
    """Verify SEFAZ NF-e v4.00 XML parser extracts <rastro> batch, <med> ANVISA, and populates Prong 1 + GraphRAG."""
    parser = NfeXmlParser()
    record = parser.parse_xml(SAMPLE_NFE_V400_XML)

    assert record.chave_acesso == "35260912345678000195550010000489121098273645"
    assert record.numero_nf == "48912"
    assert record.emitente["CNPJ"] == "12345678000195"
    assert record.emitente["CNPJ_formatted"] == "12.345.678/0001-95"
    assert record.emitente["UF"] == "SP"
    assert record.destinatario["CNPJ"] == "98765432000110"
    assert len(record.itens) == 2

    item1 = record.itens[0]
    assert item1.c_prod == "PHM-SEMAG-2026"
    assert item1.ncm == "30049069"
    assert len(item1.rastros) == 1
    assert item1.rastros[0].n_lote == "LOTE-202609B"
    assert item1.rastros[0].q_lote == 250.0
    assert item1.rastros[0].d_fab == "2026-09-01"
    assert item1.rastros[0].d_val == "2028-09-01"
    assert item1.med is not None
    assert item1.med.c_prod_anvisa == "1023504910024"
    assert item1.med.formatted_ms == "1.0235.0491.002-4"
    assert record.totais["vNF"] == 31925.00
    assert "LOTE-202609B" in record.batches_extracted
    assert "1023504910024" in record.anvisa_registrations

    # Verify ingestion into SovereignQueryRouter (Prong 1) and GraphStore
    router = SovereignQueryRouter()
    graph = GraphStore(db_path=":memory:")
    ingest_res = parser.ingest_nfe(
        SAMPLE_NFE_V400_XML,
        router=router,
        graph_store=graph,
        clearance_level=ClearanceLevel.PUBLIC,
    )
    assert ingest_res["status"] == "success"
    assert ingest_res["indexed_router_records"] >= 6
    assert ingest_res["indexed_graph_edges"] >= 5

    # Prong 1 lookup by LOTE-202609B
    lote_route = router.route_and_execute("LOTE-202609B", user_clearance="public")
    assert (lote_route.get("route_type") or lote_route.get("route")) == QueryRouteType.DETERMINISTIC_DIRECT.value
    assert len(lote_route["results"]) >= 1
    assert "1023504910024" in lote_route["results"][0]["content"]

    # Prong 1 lookup by 44-digit NF-e Chave de Acesso
    chave_route = router.route_and_execute(
        "35260912345678000195550010000489121098273645",
        user_clearance="public",
    )
    assert (chave_route.get("route_type") or chave_route.get("route")) == QueryRouteType.DETERMINISTIC_DIRECT.value
    assert len(chave_route["results"]) >= 1

    # Verify GraphRAG edges: Emitter_CNPJ --[ISSUED_NFE]--> chNFe --[CONTAINS_LOTE]--> LOTE-202609B
    dossier = graph.compile_dossier("LOTE-202609B", max_clearance=3)
    assert dossier["entity"] is not None
    rel_types = {r["relation_type"] for r in dossier["relations"]}
    assert "CONTAINS_LOTE" in rel_types
    assert "REGISTERED_ANVISA" in rel_types


def test_nfe_xml_parser_rejects_xxe_entity_expansion():
    """Verify NfeXmlParser strictly blocks <!ENTITY, SYSTEM, and PUBLIC XXE attacks."""
    malicious_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE nfeProc [
      <!ENTITY xxe SYSTEM "file:///etc/passwd">
    ]>
    <nfeProc><NFe><infNFe Id="NFe123">&xxe;</infNFe></NFe></nfeProc>
    """
    parser = NfeXmlParser()
    with pytest.raises(XmlSecurityError):
        parser.parse_xml(malicious_xml)


def test_mbox_email_parser_builds_conversational_thread_edges():
    """Verify MboxEmailParser extracts 3 threaded messages, attachments, and REPLIES_TO / CORRELATED_WITH edges."""
    parser = MboxEmailParser()
    messages = parser.parse_mbox(SAMPLE_NOC_MBOX)
    assert len(messages) == 3

    msg1, msg2, msg3 = messages
    assert msg1.message_id == "inc-2026-8841-msg1@telco-sovereign.br"
    assert msg1.in_reply_to is None
    assert "INC-2026-8841" in msg1.extracted_identifiers
    assert "ALM-26235" in msg1.extracted_identifiers
    assert "DSP OPTMODULE" in msg1.extracted_identifiers

    assert msg2.message_id == "inc-2026-8841-msg2@telco-sovereign.br"
    assert msg2.in_reply_to == "inc-2026-8841-msg1@telco-sovereign.br"
    assert "bbu5900_dsp_optmodule_slot2.log" in msg2.attachment_filenames

    assert msg3.message_id == "inc-2026-8841-msg3@telco-sovereign.br"
    assert msg3.in_reply_to == "inc-2026-8841-msg2@telco-sovereign.br"
    assert len(msg3.references) == 2

    router = SovereignQueryRouter()
    graph = GraphStore(db_path=":memory:")
    res = parser.ingest_mailbox(
        SAMPLE_NOC_MBOX,
        router=router,
        graph_store=graph,
        clearance_level=ClearanceLevel.PUBLIC,
    )
    assert res["status"] == "success"
    assert res["messages_count"] == 3

    # Prong 1 lookup for INC-2026-8841
    inc_route = router.route_and_execute("INC-2026-8841", user_clearance="public")
    assert (inc_route.get("route_type") or inc_route.get("route")) == QueryRouteType.DETERMINISTIC_DIRECT.value
    assert len(inc_route["results"]) >= 1

    # GraphRAG REPLIES_TO & CORRELATED_WITH verification
    msg2_dossier = graph.compile_dossier("inc-2026-8841-msg2@telco-sovereign.br", max_clearance=3)
    assert msg2_dossier["entity"] is not None
    rel_types = {r["relation_type"] for r in msg2_dossier["relations"]}
    assert "REPLIES_TO" in rel_types
    assert "MENTIONS_ENTITY" in rel_types


def test_tabular_csv_parser_sniffs_delimiters_and_indexes_biomarkers():
    """Verify TabularCsvParser sniffs CSV/TSV delimiters and indexes CPF + CID-10 into Prong 1 & GraphRAG."""
    parser = TabularCsvParser()
    parsed = parser.parse_tabular(SAMPLE_CLINICAL_CSV, source_name="clinical_longevity_panel.csv")
    assert parsed["detected_delimiter"] == ","
    assert parsed["row_count"] == 3
    assert "apob_mg_dl" in parsed["headers"]

    router = SovereignQueryRouter()
    graph = GraphStore(db_path=":memory:")
    res = parser.ingest_tabular(
        SAMPLE_CLINICAL_CSV,
        router=router,
        graph_store=graph,
        source_name="clinical_longevity_panel.csv",
        clearance_level=ClearanceLevel.PUBLIC,
    )
    assert res["status"] == "success"
    assert res["row_count"] == 3

    # Prong 1 lookup by Patient CPF
    cpf_route = router.route_and_execute("418.920.331-45", user_clearance="public")
    assert (cpf_route.get("route_type") or cpf_route.get("route")) == QueryRouteType.DETERMINISTIC_DIRECT.value
    assert len(cpf_route["results"]) >= 1
    assert "ApoB" in cpf_route["results"][0]["content"]

    # Prong 1 lookup by CID-10 code
    cid_route = router.route_and_execute("CID-10 E11.9", user_clearance="public")
    assert (cid_route.get("route_type") or cid_route.get("route")) == QueryRouteType.DETERMINISTIC_DIRECT.value
    assert len(cid_route["results"]) >= 1


def test_mcp_7_tools_benchmark_artifacts_exist_and_valid():
    """Verify mcp_7_tools_benchmark.json and MCP_7_TOOLS_BENCHMARK_REPORT.md were generated with all 7 tools."""
    json_path = APPLIANCE_ROOT / "benchmarks" / "mcp_7_tools_benchmark.json"
    md_path = APPLIANCE_ROOT / "benchmarks" / "MCP_7_TOOLS_BENCHMARK_REPORT.md"
    assert json_path.is_file()
    assert md_path.is_file()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_mcp_tools_exposed"] == 7
    benchmarked_tools = {b["tool_name"] for b in data["tool_benchmarks"]}
    assert len(benchmarked_tools) == 7
    assert all(b["verified"] is True for b in data["tool_benchmarks"])


def test_v2_red_team_hardening_html_mime_zero_disk_and_mcp_inspect():
    """
    Verify Staff-Architect v2 Red-Team Hardening Upgrades:
    1. HTML-only MIME email ('text/html') body extraction & identifier recognition.
    2. 100% in-memory bytes .mbox parsing (zero tempfile / zero .lock file).
    3. Deterministic SHA-256 fallback row ID in TabularCsvParser.
    4. sovereign_inspect_archive native support for .xml (NF-e), .mbox, and .csv containers.
    """
    from core.mcp.server import _fallback_inspect_archive

    html_only_eml = (
        "From: nms-alert@operadora.com.br\r\n"
        "To: noc@operadora.com.br\r\n"
        "Subject: [HTML ALERT] BBU5900 Optical Degradation\r\n"
        "Message-ID: <html-only-01@operadora.com.br>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><head><style>body { color: red; }</style></head>"
        "<body><p>Critical alarm <b>ALM-26235</b> triggered on batch <code>LOTE-202609B</code>. "
        "Execute <span>DSP OPTMODULE</span> immediately.</p></body></html>"
    )
    mbox_parser = MboxEmailParser()
    rec = mbox_parser.parse_eml(html_only_eml.encode("utf-8"))
    assert "ALM-26235" in rec.extracted_identifiers
    assert "DSP OPTMODULE" in rec.extracted_identifiers
    assert "Critical alarm ALM-26235" in rec.body_text

    # In-memory bytes .mbox parsing
    raw_mbox_bytes = (
        f"From nms@operadora.com.br Thu Sep 24 15:00:00 2026\r\n{html_only_eml}\r\n"
    ).encode("utf-8")
    mbox_records = mbox_parser.parse_mbox(raw_mbox_bytes)
    assert len(mbox_records) == 1
    assert mbox_records[0].message_id == "html-only-01@operadora.com.br"

    # Deterministic SHA-256 fallback row ID in TabularCsvParser
    csv_parser = TabularCsvParser()
    id1, _ = csv_parser._extract_row_identifiers({"metric": "Vitamin D", "value": "48 ng/mL"})
    id2, _ = csv_parser._extract_row_identifiers({"metric": "Vitamin D", "value": "48 ng/mL"})
    assert id1 == id2
    assert id1.startswith("ROW-") and len(id1) == 14

    # Native MCP sovereign_inspect_archive on .xml, .mbox, and .csv
    real_dir = APPLIANCE_ROOT / "benchmarks" / "data" / "real_formats"
    xml_inspect = _fallback_inspect_archive({"archive_path": str(real_dir / "nfe_v400_pharma_lote.xml")})
    assert xml_inspect["zero_disk_extraction"] is True
    assert "LOTE-202609B" in xml_inspect["nfe_invoice_summary"]["batches_extracted"]

    mbox_inspect = _fallback_inspect_archive({"archive_path": str(real_dir / "noc_incident_thread.mbox")})
    assert mbox_inspect["zero_disk_extraction"] is True
    assert mbox_inspect["total_entries"] == 3

    csv_inspect = _fallback_inspect_archive({"archive_path": str(real_dir / "clinical_longevity_panel.csv")})
    assert csv_inspect["zero_disk_extraction"] is True
    assert csv_inspect["total_entries"] == 3

