#!/usr/bin/env python3
"""
Phase 10.4 (Task 4.1) — Multi-Hop Graph Enrichment for Huawei 26.1.0 .xlsx Performance Counters,
Northbound Events, and Deep Alarm-to-MML/Counter Relationships.

Streams directly in-memory from `/home/tlima/Enterprise_Hub/docs/Hua_Docs/` and enriches:
- `sovereign_huawei_router.db` (Performance Counter & Event spreadsheet rows)
- `sovereign_huawei_graph.db` (`DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`, `MEASURED_BY_COUNTER`, `HAS_DIAGRAM` edges)
"""

import io
import json
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple

from core.formats.openxml_parser import OpenXmlReleaseDocParser
from core.graph.store import GraphStore

HUA_DOCS_DIR = Path("/home/tlima/Enterprise_Hub/docs/Hua_Docs")
ROUTER_DB_PATH = Path("/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/data/sovereign_huawei_router.db")
GRAPH_DB_PATH = Path("/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/data/sovereign_huawei_graph.db")

MML_PATTERN = re.compile(
    r"\b((?:ADD|MOD|RMV|LST|DSP|SET|ACT|DEA|CLR|COL|RST|SWP|PING|TRC|NGPING|NGTRACEROUTE)(?:\s+[A-Z0-9_]{2,20})?)\b"
)
IMG_SRC_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+\.(?:png|jpg|gif))["\']', re.I)


def _ensure_entity(cur: sqlite3.Cursor, name: str, entity_type: str, clearance: int = 1) -> int:
    norm = name.strip().lower()
    cur.execute(
        "SELECT id FROM entities WHERE normalized_name = ? AND entity_type = ?",
        (norm, entity_type),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT OR IGNORE INTO entities (name, normalized_name, entity_type, clearance_level) VALUES (?, ?, ?, ?)",
        (name.strip(), norm, entity_type, clearance),
    )
    cur.execute(
        "SELECT id FROM entities WHERE normalized_name = ? AND entity_type = ?",
        (norm, entity_type),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _ensure_relation(
    cur: sqlite3.Cursor,
    src_id: int,
    tgt_id: int,
    rel_type: str,
    doc_id: int = 1,
    clearance: int = 1,
) -> int:
    if not src_id or not tgt_id or src_id == tgt_id:
        return 0
    cur.execute(
        """
        INSERT OR IGNORE INTO entity_relations
        (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
        VALUES (?, ?, ?, ?, ?)
        """,
        (src_id, tgt_id, rel_type, doc_id, clearance),
    )
    return cur.rowcount


def enrich_alarms_and_counters() -> Dict[str, int]:
    t0 = time.perf_counter()
    rconn = sqlite3.connect(str(ROUTER_DB_PATH))
    rcur = rconn.cursor()

    gstore = GraphStore(GRAPH_DB_PATH)
    gconn = gstore._conn
    gcur = gconn.cursor()

    # Ensure a master document anchor in GraphStore
    gcur.execute(
        "INSERT OR IGNORE INTO documents (corpus, doc_identifier, title, url, clearance_level) VALUES (?, ?, ?, ?, ?)",
        (
            "huawei_26_1_0",
            "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs",
            "Huawei 26.1.0 USC & UPCF Master Knowledge Graph",
            "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs",
            1,
        ),
    )
    gcur.execute("SELECT id FROM documents LIMIT 1")
    master_doc_id = int(gcur.fetchone()[0])

    stats = {
        "alarms_parsed_for_edges": 0,
        "mml_edges_added": 0,
        "diagram_edges_added": 0,
        "counter_records_indexed": 0,
        "counter_edges_added": 0,
    }

    # 1. Enrich all alarm HTML pages across USC 26.1.0 and UPCF 26.1.0 with full 12K bodies & Graph edges
    hwics_packages = [
        ("USC 26.1.0", HUA_DOCS_DIR / "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip"),
        ("UPCF 26.1.0", HUA_DOCS_DIR / "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip"),
    ]

    for prod_label, zip_path in hwics_packages:
        if not zip_path.exists():
            continue
        with zipfile.ZipFile(zip_path, "r") as ozf:
            hw_name = ozf.infolist()[0].filename
            hw_bytes = ozf.read(hw_name)
        with zipfile.ZipFile(io.BytesIO(hw_bytes), "r") as izf:
            for info in izf.infolist():
                ep = info.filename
                if not ep.endswith(".html") or ("/alarms/" not in ep and "alarm" not in ep):
                    continue
                stem = Path(ep).stem
                if not stem.isdigit():
                    continue
                alm_code = f"ALM-{stem}"
                raw_html = izf.read(ep).decode("utf-8", errors="ignore")

                # Extract title
                m_title = re.search(r"<title>(.*?)</title>", raw_html, flags=re.I | re.S)
                page_title = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else alm_code
                if not page_title.upper().startswith("ALM-"):
                    page_title = f"{alm_code} {page_title}"

                # Clean full HTML text up to 12,000 chars so Possible Causes & Procedure are never cut off
                txt_clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.S | re.I)
                txt_clean = re.sub(r"<[^>]+>", "\n", txt_clean)
                lines = [re.sub(r"\s+", " ", l).strip() for l in txt_clean.splitlines() if l.strip()]
                full_body = "\n".join(lines)[:12000]
                v_uri = f"archive://{zip_path}!{hw_name}#{ep}"
                enriched_content = f"[{prod_label} > {ep}]\nTitle: {page_title}\nVirtual URI: {v_uri}\n\n{full_body}"

                rcur.execute(
                    "UPDATE document_records SET content = ? WHERE doc_identifier = ? AND LENGTH(content) < ?",
                    (enriched_content, v_uri, len(enriched_content)),
                )

                # Register alarm entity in GraphStore
                alm_ent_id = _ensure_entity(gcur, f"{alm_code} ({page_title[:65]})", "telecom_alarm")
                short_alm_id = _ensure_entity(gcur, alm_code, "telecom_alarm")
                _ensure_relation(gcur, short_alm_id, alm_ent_id, "CANONICAL_ALARM_SPEC", master_doc_id)
                stats["alarms_parsed_for_edges"] += 1

                # Split into Description/Parameters vs Procedure to classify MML commands accurately
                proc_idx = full_body.lower().rfind("\nprocedure\n")
                desc_part = full_body[:proc_idx] if proc_idx != -1 else full_body
                proc_part = full_body[proc_idx:] if proc_idx != -1 else full_body

                for mml in set(MML_PATTERN.findall(desc_part)):
                    if mml in ("ADD", "MOD", "RMV", "LST", "DSP", "SET", "ACT", "DEA", "CLR", "COL", "RST"):
                        continue
                    mml_id = _ensure_entity(gcur, mml, "mml_command")
                    stats["mml_edges_added"] += _ensure_relation(gcur, short_alm_id, mml_id, "CONFIGURED_BY_MML", master_doc_id)

                for mml in set(MML_PATTERN.findall(proc_part)):
                    if mml in ("ADD", "MOD", "RMV", "LST", "DSP", "SET", "ACT", "DEA", "CLR", "COL", "RST"):
                        continue
                    mml_id = _ensure_entity(gcur, mml, "mml_command")
                    rel = (
                        "DIAGNOSED_BY_MML"
                        if mml.startswith(("LST", "DSP", "NGPING", "NGTRACEROUTE", "PING", "TRC", "COL"))
                        else "REMEDIATED_BY_MML"
                    )
                    stats["mml_edges_added"] += _ensure_relation(gcur, short_alm_id, mml_id, rel, master_doc_id)

                # Extract embedded <img src="figure/..."> ladder / root-alarm diagrams
                parent_dir = str(Path(ep).parent)
                for img_rel in set(IMG_SRC_PATTERN.findall(raw_html)):
                    norm_img = str((Path(parent_dir) / img_rel).as_posix())
                    img_uri = f"archive://{zip_path}!{hw_name}#{norm_img}"
                    diag_id = _ensure_entity(gcur, img_uri, "visual_plate")
                    stats["diagram_edges_added"] += _ensure_relation(gcur, short_alm_id, diag_id, "HAS_DIAGRAM", master_doc_id)

    # 2. Parse Performance Counter List .xlsx workbooks from ReleaseDoc ZIPs and wire MEASURED_BY_COUNTER edges
    parser = OpenXmlReleaseDocParser()
    release_zips = [
        ("UPCF 26.1.0.5", HUA_DOCS_DIR / "UPCF 26.1.0.5_ReleaseDoc_EN (Virtual Machine Container).zip"),
        ("USC 26.1.0", HUA_DOCS_DIR / "USC 26.1.0_ReleaseDoc_EN (VM).zip"),
    ]

    # Key domain links mapping counter families to their monitored Huawei alarms & 5G PCC / BSF entities
    domain_counter_links: List[Tuple[re.Pattern, List[Tuple[str, str]]]] = [
        (
            re.compile(r"\b(SCTP|Diameter|DMLNK|M3UA|M2PA|retransmission|delay|link\s+bear)\b", re.I),
            [
                ("ALM-20104", "telecom_alarm"),
                ("ALM-20333", "telecom_alarm"),
                ("ALM-22900", "telecom_alarm"),
            ],
        ),
        (
            re.compile(r"\b(Npcf|SMPolicy|AMPolicy|PCC|QoS|UsageReport|Quota|5GFUP)\b", re.I),
            [
                ("WHFD-611001 5GFUP_Service", "telecom_feature"),
                ("Level 1: Service (5G PCC)", "pcc_level_1"),
                ("Level 4: Rule (DynamicPccRule / Predefined Rule)", "pcc_level_4"),
            ],
        ),
        (
            re.compile(r"\b(BSF|Binding|Session\s+Binding|IMSIBIND|Rx|Nbsf)\b", re.I),
            [
                ("USCFD-012001 HTTP Signaling Session Binding", "telecom_feature"),
                ("USCDB", "database_engine"),
            ],
        ),
    ]

    for rel_label, rzip in release_zips:
        if not rzip.exists():
            continue
        with zipfile.ZipFile(rzip, "r") as zf:
            for info in zf.infolist():
                fn = info.filename
                if not fn.lower().endswith(".xlsx") or "counter" not in fn.lower():
                    continue
                xlsx_bytes = zf.read(fn)
                wb_uri = f"archive://{rzip}#{fn}"
                _, _, counters = parser.parse_xlsx_bytes(xlsx_bytes, wb_uri)
                wb_ent_id = _ensure_entity(gcur, Path(fn).name, "openxml_workbook")

                high_signal_counters = []
                for c in counters:
                    c_txt = (
                        f"Counter ID: {c.counter_id} | Name: {c.counter_name} | "
                        f"Object: {c.object_name} | Function Set: {c.function_set_name} / {c.function_subset_name} | "
                        f"Unit: {c.unit} | NE: {c.affected_ne}"
                    )
                    if any(rx.search(c_txt) for rx, _ in domain_counter_links):
                        high_signal_counters.append((c, c_txt))

                for batch_idx in range(0, min(len(high_signal_counters), 300), 12):
                    batch = high_signal_counters[batch_idx : batch_idx + 12]
                    batch_body = "\n".join(item[1] for item in batch)
                    sh_name = batch[0][0].sheet_name if batch else "Counters"
                    doc_id_str = f"{wb_uri}#{sh_name}_rows_{batch_idx}"
                    title_str = f"{rel_label} Performance Counters — {Path(fn).name} ({sh_name} #{batch_idx // 12 + 1})"
                    full_text = f"[{title_str}]\nVirtual URI: {doc_id_str}\n\n{batch_body}"

                    rcur.execute(
                        """
                        INSERT OR REPLACE INTO document_records
                        (doc_identifier, title, content, clearance_level, metadata)
                        VALUES (?, ?, ?, 1, ?)
                        """,
                        (
                            doc_id_str,
                            title_str,
                            full_text,
                            json.dumps({"virtual_uri": doc_id_str, "source_type": "openxml_counter_matrix"}),
                        ),
                    )
                    stats["counter_records_indexed"] += 1

                    for c_obj, r_txt in batch[:5]:
                        counter_label = f"{c_obj.counter_id} ({c_obj.counter_name[:55]})"
                        cnt_ent_id = _ensure_entity(gcur, f"KPI: {counter_label}", "telecom_kpi")
                        _ensure_relation(gcur, cnt_ent_id, wb_ent_id, "DEFINED_IN_WORKBOOK", master_doc_id)
                        for rx, targets in domain_counter_links:
                            if rx.search(r_txt):
                                for tgt_name, tgt_type in targets:
                                    tgt_id = _ensure_entity(gcur, tgt_name, tgt_type)
                                    stats["counter_edges_added"] += _ensure_relation(
                                        gcur, tgt_id, cnt_ent_id, "MEASURED_BY_COUNTER", master_doc_id
                                    )

    # Explicit guaranteed deterministic graph edges for ALM-20104 & ALM-20333 (Link Bear Quality)
    for alm_code, alm_desc, link_mml in [
        ("ALM-20104", "ALM-20104 Link Bear Quality (Diameter Link)", "ADD DMLNK"),
        ("ALM-20333", "ALM-20333 STP Link Bear Quality (M3UA/M2PA Link)", "ADD M3LNK"),
    ]:
        aid = _ensure_entity(gcur, alm_code, "telecom_alarm")
        for mml_cmd, rel in [
            ("NGPING (Packet Count=600, TimeOut=1500ms)", "DIAGNOSED_BY_MML"),
            ("LST IPADDR", "DIAGNOSED_BY_MML"),
            ("NGTRACEROUTE", "DIAGNOSED_BY_MML"),
            ("LST SCTPPP", "DIAGNOSED_BY_MML"),
            ("MOD SCTPPP (RTR=5, AAD=1000, ADEV=5000)", "REMEDIATED_BY_MML"),
            ("ADD SCTPPP", "CONFIGURED_BY_MML"),
            (link_mml, "CONFIGURED_BY_MML"),
        ]:
            mid = _ensure_entity(gcur, mml_cmd, "mml_command")
            stats["mml_edges_added"] += _ensure_relation(gcur, aid, mid, rel, master_doc_id)
        for kpi_name in [
            "KPI: SCTP Retransmission Ratio Threshold (RTR Default=5%)",
            "KPI: SCTP Average Acknowledgement Delay Threshold (AAD Default=1000ms)",
            "KPI: SCTP Average Deviation Threshold (ADEV Default=5000ms)",
        ]:
            kid = _ensure_entity(gcur, kpi_name, "telecom_kpi")
            stats["counter_edges_added"] += _ensure_relation(gcur, aid, kid, "MEASURED_BY_COUNTER", master_doc_id)

    rcur.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
    rconn.commit()
    gconn.commit()
    rconn.close()
    gstore.close()
    stats["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    return stats


if __name__ == "__main__":
    res = enrich_alarms_and_counters()
    print(json.dumps(res, indent=2))
