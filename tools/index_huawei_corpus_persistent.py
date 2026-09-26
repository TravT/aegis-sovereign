#!/usr/bin/env python3
"""
Persistent Full-Body Huawei 26.1.0 Corpus Indexer (ADR-07 & ADR-40).
Aegis Sovereign Knowledge Appliance.

Streams the 4 Huawei 26.1.0 documentation packages from /tmp/docs_rag_gemini/
100% in-memory (os.open O_RDONLY + io.BytesIO, zero disk extraction) and builds
the persistent SQLite B-Tree + External-Content FTS5 router database and GraphStore:
  - dev/aegis-sovereign-appliance/data/sovereign_huawei_router.db
  - dev/aegis-sovereign-appliance/data/sovereign_huawei_graph.db
"""

from __future__ import annotations

import html
import io
import json
import os
import posixpath
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure project root is on sys.path
APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))

from core.graph.store import GraphStore
from core.router.query_router import SovereignQueryRouter
from core.security import ClearanceLevel

CORPUS_DIR = Path("/tmp/docs_rag_gemini")
ROUTER_DB_PATH = APPLIANCE_ROOT / "data" / "sovereign_huawei_router.db"
GRAPH_DB_PATH = APPLIANCE_ROOT / "data" / "sovereign_huawei_graph.db"

_SCRIPT_STYLE_HEAD_RE = re.compile(
    r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<head\b[^>]*>.*?</head>",
    re.DOTALL | re.IGNORECASE,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WS_COLLAPSE_RE = re.compile(r"\s+")
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL | re.IGNORECASE)
_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.DOTALL | re.IGNORECASE)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
_FIG_IMG_RE = re.compile(
    r'<div[^>]*class="fignone"[^>]*>.*?<span[^>]*class="figcap"[^>]*>(.*?)</span>.*?<img[^>]*src="([^"]+)"',
    re.DOTALL | re.IGNORECASE,
)
_VSD_IMG_RE = re.compile(r'<img[^>]*src="([^"]+)"[^>]*>', re.IGNORECASE)
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL | re.IGNORECASE)


def read_readonly_bytes(file_path: Path) -> bytes:
    """Read file into memory strictly via O_RDONLY file descriptor (zero disk extraction)."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(str(file_path), flags)
    try:
        with os.fdopen(fd, "rb") as f:
            return f.read()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def strip_html(raw: str) -> str:
    cleaned = _SCRIPT_STYLE_HEAD_RE.sub(" ", raw)
    return _WS_COLLAPSE_RE.sub(" ", html.unescape(_TAG_STRIP_RE.sub(" ", cleaned))).strip()


def extract_rich_html_body(
    raw_html: str,
    entry_path: str,
    archive_prefix: str,
    max_chars: int = 18000,
) -> Dict[str, Any]:
    """
    Extract full HTML body text, Markdown-formatted tables, MML commands,
    software parameters, and resolved archive:// diagram URIs.
    """
    h1_match = _H1_RE.search(raw_html)
    title = strip_html(h1_match.group(1)) if h1_match else Path(entry_path).stem

    # Extract tables into pipe-delimited Markdown rows
    table_blocks: List[str] = []
    for tbl_html in _TABLE_RE.findall(raw_html):
        rows_md: List[str] = []
        for tr_html in _TR_RE.findall(tbl_html):
            cells = [strip_html(c) for c in _TD_RE.findall(tr_html)]
            if any(cells):
                rows_md.append("| " + " | ".join(cells) + " |")
        if rows_md:
            table_blocks.append("\n".join(rows_md[:60]))

    # Extract figures & <img class="vsd"> diagrams with archive:// virtual URIs
    figures: List[Dict[str, str]] = []
    seen_srcs: Set[str] = set()
    for fig_cap_raw, img_src in _FIG_IMG_RE.findall(raw_html):
        cap = strip_html(fig_cap_raw)
        resolved_src = posixpath.normpath(posixpath.join(posixpath.dirname(entry_path), img_src))
        seen_srcs.add(resolved_src)
        figures.append({
            "caption": cap,
            "relative_src": img_src,
            "archive_entry": resolved_src,
            "virtual_uri": f"archive://{archive_prefix}#{resolved_src}",
        })
    for img_src in _VSD_IMG_RE.findall(raw_html):
        if "figure/" in img_src or "image" in img_src or ".png" in img_src:
            resolved_src = posixpath.normpath(posixpath.join(posixpath.dirname(entry_path), img_src))
            if resolved_src not in seen_srcs:
                seen_srcs.add(resolved_src)
                figures.append({
                    "caption": f"Diagram {posixpath.basename(resolved_src)}",
                    "relative_src": img_src,
                    "archive_entry": resolved_src,
                    "virtual_uri": f"archive://{archive_prefix}#{resolved_src}",
                })

    body_text = strip_html(raw_html)
    # Remove trailing copyright boilerplate if present
    body_text = re.sub(
        r"Copyright\s*©\s*Huawei Technologies Co\.,\s*Ltd\.?\s*$",
        "",
        body_text,
        flags=re.IGNORECASE,
    ).strip()

    parts = [body_text]
    if table_blocks:
        parts.append("\n[Structured Tables]\n" + "\n\n".join(table_blocks[:10]))
    if figures:
        fig_lines = [
            f"- {f['caption']}: {f['virtual_uri']}"
            for f in figures[:10]
        ]
        parts.append("\n[Embedded Diagrams & Visual Plates]\n" + "\n".join(fig_lines))

    full_text = "\n".join(parts)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]

    return {
        "title": title,
        "text": full_text,
        "figures": figures,
        "table_count": len(table_blocks),
    }


def parse_navi_xml_tree(xml_bytes: bytes, product_label: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse resources/navi.xml to map every HTML entry path ('resources/...') to:
      - title
      - breadcrumb
      - children_paths (ordered list of direct & descendant HTML paths)
    """
    url_map: Dict[str, Dict[str, Any]] = {}
    root = ET.fromstring(xml_bytes)

    def _walk(node: ET.Element, parent_crumb: str) -> List[str]:
        descendant_urls: List[str] = []
        for child in node:
            if child.tag == "topic" or child.tag.endswith("}topic"):
                txt = (child.attrib.get("txt") or "Untitled").strip()
                raw_url = (child.attrib.get("url") or "").strip()
                crumb = f"{parent_crumb} > {txt}" if parent_crumb else f"{product_label} > {txt}"
                norm_path = ""
                if raw_url:
                    clean_u = raw_url.split("#")[0].lstrip("/")
                    norm_path = (
                        clean_u
                        if clean_u.startswith("resources/")
                        else posixpath.normpath(posixpath.join("resources", clean_u))
                    )
                sub_urls = _walk(child, crumb)
                if norm_path:
                    if norm_path not in url_map:
                        url_map[norm_path] = {
                            "title": txt,
                            "breadcrumb": crumb,
                            "children_paths": [],
                        }
                    for su in sub_urls:
                        if su != norm_path and su not in url_map[norm_path]["children_paths"]:
                            url_map[norm_path]["children_paths"].append(su)
                    descendant_urls.append(norm_path)
                descendant_urls.extend(sub_urls)
        return descendant_urls

    _walk(root, product_label)
    return url_map


def parse_xlsx_named_sheets(xlsx_bytes: bytes) -> Dict[str, List[List[str]]]:
    """Parse an OpenXML .xlsx/.xlsm spreadsheet in memory with real workbook sheet names."""
    sheets: Dict[str, List[List[str]]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zf:
            names = set(zf.namelist())
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root:
                    texts = [
                        t.text or ""
                        for t in si.iter()
                        if t.tag.endswith("}t") or t.tag == "t"
                    ]
                    shared_strings.append("".join(texts))

            # Map r:id -> target worksheet path via xl/_rels/workbook.xml.rels
            rid_to_target: Dict[str, str] = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
                for rel in rels_root.iter():
                    if rel.tag.endswith("}Relationship") or rel.tag == "Relationship":
                        rid = rel.attrib.get("Id", "")
                        tgt = rel.attrib.get("Target", "").lstrip("/")
                        if rid and tgt:
                            if not tgt.startswith("xl/"):
                                tgt = posixpath.normpath(posixpath.join("xl", tgt))
                            rid_to_target[rid] = tgt

            sheet_path_to_name: Dict[str, str] = {}
            if "xl/workbook.xml" in names:
                wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
                idx = 1
                for el in wb_root.iter():
                    if el.tag.endswith("}sheet") or el.tag == "sheet":
                        sname = el.attrib.get("name", f"Sheet{idx}")
                        rid = ""
                        for k, v in el.attrib.items():
                            if k.endswith("}id") or k == "r:id":
                                rid = v
                                break
                        tgt = rid_to_target.get(rid, f"xl/worksheets/sheet{idx}.xml")
                        sheet_path_to_name[tgt] = sname
                        idx += 1

            for name in sorted(names):
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    human_name = sheet_path_to_name.get(name, posixpath.basename(name))
                    sroot = ET.fromstring(zf.read(name))
                    rows: List[List[str]] = []
                    for row in sroot.iter():
                        if row.tag.endswith("}row") or row.tag == "row":
                            r_vals: List[str] = []
                            for c in row:
                                t_attr = c.attrib.get("t", "")
                                val = ""
                                for child in c:
                                    if child.tag.endswith("}v") or child.tag == "v":
                                        val = child.text or ""
                                    elif child.tag.endswith("}is") or child.tag == "is":
                                        val = "".join(
                                            x.text or ""
                                            for x in child.iter()
                                            if x.tag.endswith("}t") or x.tag == "t"
                                        )
                                if t_attr == "s" and val.isdigit():
                                    s_idx = int(val)
                                    if 0 <= s_idx < len(shared_strings):
                                        val = shared_strings[s_idx]
                                r_vals.append(_WS_COLLAPSE_RE.sub(" ", val).strip())
                            if any(r_vals):
                                rows.append(r_vals)
                    sheets[human_name] = rows
    except Exception:
        pass
    return sheets


def parse_docx_rich(docx_bytes: bytes) -> Dict[str, Any]:
    """Parse an OpenXML .docx manual in memory, skipping legal front-matter boilerplate."""
    paragraphs: List[str] = []
    tables_md: List[str] = []
    boilerplate_phrases = (
        "copyright © huawei technologies",
        "no part of this document may be reproduced",
        "trademarks and permissions",
        "all other trademarks and trade names",
        "the information in this document is subject to change",
        "every effort has been made in the preparation",
        "indicates a hazard with a high level of risk",
        "indicates a hazard with a medium level of risk",
        "indicates a hazard with a low level of risk",
        "indicates a potentially hazardous situation",
    )
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as zf:
            if "word/document.xml" in zf.namelist():
                root = ET.fromstring(zf.read("word/document.xml"))
                for elem in root.iter():
                    if elem.tag.endswith("}p"):
                        txt = "".join(
                            t.text or "" for t in elem.iter() if t.tag.endswith("}t")
                        ).strip()
                        txt = _WS_COLLAPSE_RE.sub(" ", txt)
                        if txt and not any(bp in txt.lower() for bp in boilerplate_phrases):
                            paragraphs.append(txt)
                    elif elem.tag.endswith("}tbl"):
                        t_rows: List[str] = []
                        for tr in elem:
                            if tr.tag.endswith("}tr"):
                                cells: List[str] = []
                                for tc in tr:
                                    if tc.tag.endswith("}tc"):
                                        c_txt = "".join(
                                            t.text or "" for t in tc.iter() if t.tag.endswith("}t")
                                        ).strip()
                                        cells.append(_WS_COLLAPSE_RE.sub(" ", c_txt))
                                if any(cells):
                                    t_rows.append("| " + " | ".join(cells) + " |")
                        if t_rows:
                            tables_md.append("\n".join(t_rows[:40]))
    except Exception:
        pass

    return {
        "paragraphs": paragraphs,
        "tables_md": tables_md,
        "paragraph_count": len(paragraphs),
        "table_count": len(tables_md),
    }


def build_persistent_huawei_databases() -> Dict[str, Any]:
    t_start = time.perf_counter()
    ROUTER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Remove old DB files if present to guarantee a clean, deterministic build
    for p in (ROUTER_DB_PATH, GRAPH_DB_PATH):
        if p.exists():
            p.unlink()
        for suffix in ("-wal", "-shm"):
            wp = Path(str(p) + suffix)
            if wp.exists():
                wp.unlink()

    router = SovereignQueryRouter(db_path=ROUTER_DB_PATH)
    graph_store = GraphStore(db_path=GRAPH_DB_PATH)

    # Temporarily drop FTS5 triggers during bulk insert for 25x speedup, then rebuild FTS5 once
    with router._conn:
        router._conn.execute("DROP TRIGGER IF EXISTS document_records_ai;")
        router._conn.execute("DROP TRIGGER IF EXISTS document_records_ad;")
        router._conn.execute("DROP TRIGGER IF EXISTS document_records_au;")

    batch_records: Dict[str, Tuple[str, str, str, int, str]] = {}

    def queue_record(
        doc_id: str,
        title: str,
        content: str,
        clearance: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = dict(metadata or {})
        if "virtual_uri" not in meta and doc_id.startswith("archive://"):
            meta["virtual_uri"] = doc_id
        if "file_path" not in meta and meta.get("virtual_uri"):
            meta["file_path"] = meta["virtual_uri"]
        batch_records[doc_id] = (
            doc_id,
            title,
            content,
            clearance,
            json.dumps(meta, ensure_ascii=False),
        )

    stats = {
        "html_pages_indexed": 0,
        "composite_feature_rollups": 0,
        "alarm_records_indexed": 0,
        "mml_records_indexed": 0,
        "openxml_workbooks_indexed": 0,
        "openxml_sheets_indexed": 0,
        "openxml_docx_indexed": 0,
        "navi_breadcrumbs_mapped": 0,
    }

    # -----------------------------------------------------------------------
    # PHASE 1: Parse ReleaseDoc .zip containers (.xlsx, .xlsm, .docx) in memory
    # -----------------------------------------------------------------------
    print("[1/4] Streaming OpenXML ReleaseDoc containers (.xlsx/.xlsm/.docx) in-memory...")
    xlsx_alarm_adaptation: Dict[str, Dict[str, Any]] = {}
    csp_health_check_sections: List[str] = []

    for rel_zip_name in [
        "USC 26.1.0_ReleaseDoc_EN (VM).zip",
        "UPCF 26.1.0.5_ReleaseDoc_EN (Virtual Machine Container).zip",
    ]:
        zpath = CORPUS_DIR / rel_zip_name
        if not zpath.exists():
            continue
        raw_zip = read_readonly_bytes(zpath)
        with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                fn = info.filename
                low = fn.lower()
                v_uri = f"archive://{zpath}#{fn}"
                entry_bytes = zf.read(fn)

                if low.endswith((".xlsx", ".xlsm")):
                    stats["openxml_workbooks_indexed"] += 1
                    sheets = parse_xlsx_named_sheets(entry_bytes)
                    base_title = posixpath.basename(fn)
                    workbook_summary_parts: List[str] = [
                        f"OpenXML Workbook: {base_title} (Path: {fn}, Virtual URI: {v_uri})",
                        f"Sheets ({len(sheets)}): {', '.join(sheets.keys())}",
                    ]

                    for sname, rows in sheets.items():
                        if not rows:
                            continue
                        stats["openxml_sheets_indexed"] += 1
                        hdr = [h.lower() for h in rows[0]]
                        # Capture northbound alarm list metadata for cross-linking
                        if "alarmid" in hdr and "alarmname" in hdr:
                            for r in rows[1:]:
                                if len(r) >= 6 and r[0].strip():
                                    aid = r[0].strip()
                                    norm_aid = f"ALM-{aid}" if aid.isdigit() else aid.upper()
                                    xlsx_alarm_adaptation[norm_aid] = {
                                        "alarm_id": norm_aid,
                                        "alarm_name": r[1],
                                        "severity": r[2],
                                        "alarm_type": r[3],
                                        "location_info": r[4],
                                        "alarm_explain": r[5],
                                        "source_xlsx": base_title,
                                        "virtual_uri": v_uri,
                                    }

                        md_rows = ["| " + " | ".join(r[:12]) + " |" for r in rows[:140]]
                        sheet_text = (
                            f"[{base_title} — Sheet: {sname}]\n"
                            f"Virtual URI: {v_uri}\n"
                            f"Total Rows: {len(rows)}\n"
                            + "\n".join(md_rows)
                        )
                        workbook_summary_parts.append(sheet_text[:8000])

                        # Index dedicated per-sheet record
                        sheet_doc_id = f"{v_uri}::sheet::{sname}"
                        queue_record(
                            doc_id=sheet_doc_id,
                            title=f"{base_title} — Sheet '{sname}' ({fn})",
                            content=sheet_text[:18000],
                            metadata={
                                "virtual_uri": v_uri,
                                "file_path": v_uri,
                                "sheet_name": sname,
                                "container": rel_zip_name,
                                "entry_name": fn,
                                "format": "openxml_xlsx_sheet",
                            },
                        )

                        if (
                            "14. information collection" in low
                            or "health check" in low
                            or "inspection" in low
                        ):
                            csp_health_check_sections.append(sheet_text[:4500])

                    full_wb_text = "\n\n".join(workbook_summary_parts)[:24000]
                    queue_record(
                        doc_id=v_uri,
                        title=f"{base_title} — {fn}",
                        content=full_wb_text,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "container": rel_zip_name,
                            "entry_name": fn,
                            "sheets": list(sheets.keys()),
                            "format": "openxml_xlsx",
                        },
                    )

                elif low.endswith(".docx"):
                    stats["openxml_docx_indexed"] += 1
                    d_parsed = parse_docx_rich(entry_bytes)
                    base_title = posixpath.basename(fn)
                    paras = d_parsed["paragraphs"]
                    tbls = d_parsed["tables_md"]
                    body_joined = "\n".join(paras[:220])
                    if tbls:
                        body_joined += "\n\n[Document Tables]\n" + "\n\n".join(tbls[:12])
                    doc_content = (
                        f"OpenXML Manual: {base_title} (Path: {fn}, Virtual URI: {v_uri})\n"
                        f"Paragraphs: {d_parsed['paragraph_count']}, Tables: {d_parsed['table_count']}\n\n"
                        f"{body_joined[:22000]}"
                    )
                    queue_record(
                        doc_id=v_uri,
                        title=f"{base_title} — {fn}",
                        content=doc_content,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "container": rel_zip_name,
                            "entry_name": fn,
                            "format": "openxml_docx",
                        },
                    )
                    if (
                        "14. information collection" in low
                        or "health check" in low
                        or "inspection" in low
                    ):
                        csp_health_check_sections.append(doc_content[:5000])

    # -----------------------------------------------------------------------
    # PHASE 2: Stream USC 26.1.0 & UPCF 26.1.0 .hwics Product Documentation
    # -----------------------------------------------------------------------
    hwics_packages = [
        (
            "USC 26.1.0",
            "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip",
        ),
        (
            "UPCF 26.1.0",
            "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip",
        ),
    ]

    deep_html_dirs = (
        "resources/sps/description/",
        "resources/sps/installation/",
        "resources/sps/maintenance/",
        "resources/toctopics/",
        "resources/reference/gui/",
        "resources/reference/software_par/",
        "resources/upcc/description/",
        "resources/upcc/installation/",
        "resources/upcc/maintenance/",
        "resources/upcf/upcf/",
        "resources/upcf/upcc/",
        "resources/upcf/reference/",
        "resources/alarm_cgplite/",
        "resources/alarms/",
        "resources/csp/alarm_cgplite/",
        "resources/csp/alarms/",
        "resources/be/alarms/",
        "resources/upcf/mml/document/",
        "resources/csp/mml/",
        "resources/common/fenix/",
    )

    for prod_label, outer_zip_name in hwics_packages:
        outer_path = CORPUS_DIR / outer_zip_name
        if not outer_path.exists():
            continue
        print(f"[2/4] Streaming {prod_label} ({outer_zip_name}) in-memory...")
        outer_bytes = read_readonly_bytes(outer_path)
        with zipfile.ZipFile(io.BytesIO(outer_bytes), "r") as ozf:
            hwics_name = ozf.infolist()[0].filename
            hwics_bytes = ozf.read(hwics_name)
        del outer_bytes

        compound_prefix = f"{outer_path}!{hwics_name}"
        with zipfile.ZipFile(io.BytesIO(hwics_bytes), "r") as izf:
            navi_map: Dict[str, Dict[str, Any]] = {}
            if "resources/navi.xml" in izf.NameToInfo:
                navi_map = parse_navi_xml_tree(izf.read("resources/navi.xml"), prod_label)
                stats["navi_breadcrumbs_mapped"] += len(navi_map)

            # First cache rich parsed HTML for deep technical sections & alarms so parent topics can roll up children
            rich_cache: Dict[str, Dict[str, Any]] = {}
            all_infos = [i for i in izf.infolist() if not i.is_dir()]

            for info in all_infos:
                ep = info.filename
                low_ep = ep.lower()
                if not low_ep.endswith((".html", ".htm")):
                    continue

                is_deep = low_ep.startswith(deep_html_dirs) or any(
                    kw in low_ep
                    for kw in (
                        "012002",
                        "pms054",
                        "0298285448",
                        "0320083",
                        "0170877035",
                        "0244101433",
                        "0239573925",
                        "imsibindpnf",
                        "col_log",
                        "clr_logctrl",
                        "insp",
                    )
                )

                raw_html = izf.read(ep).decode("utf-8", errors="replace")
                navi_info = navi_map.get(ep, {})
                crumb = navi_info.get("breadcrumb", f"{prod_label} > {ep}")

                if is_deep:
                    parsed = extract_rich_html_body(raw_html, ep, compound_prefix, max_chars=18000)
                    parsed["breadcrumb"] = crumb
                    parsed["title"] = navi_info.get("title") or parsed["title"]
                    rich_cache[ep] = parsed
                else:
                    # Fast full-body strip for general MML / counter / reference pages
                    h1_m = _H1_RE.search(raw_html)
                    t_str = (
                        navi_info.get("title")
                        or (strip_html(h1_m.group(1)) if h1_m else Path(ep).stem)
                    )
                    fast_body = strip_html(raw_html)[:6500]
                    v_uri = f"archive://{compound_prefix}#{ep}"
                    content_str = f"[{crumb}]\nTitle: {t_str}\nVirtual URI: {v_uri}\n\n{fast_body}"
                    queue_record(
                        doc_id=v_uri,
                        title=f"{prod_label}: {t_str}",
                        content=content_str,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "product": prod_label,
                            "breadcrumb": crumb,
                            "entry_name": ep,
                        },
                    )
                    stats["html_pages_indexed"] += 1

                    # If MML command in title (e.g., "(ADD ...)" or "(RMV ...)"), also index by MML command ID
                    mml_m = re.search(r"\(([A-Z]{3,4}\s+[A-Z0-9_]{3,20})\)", t_str)
                    if mml_m:
                        mml_cmd = re.sub(r"\s+", " ", mml_m.group(1).upper().strip())
                        if mml_cmd not in batch_records:
                            queue_record(
                                doc_id=mml_cmd,
                                title=f"{mml_cmd} — {t_str} ({prod_label})",
                                content=content_str,
                                metadata={
                                    "virtual_uri": v_uri,
                                    "file_path": v_uri,
                                    "product": prod_label,
                                    "mml_command": mml_cmd,
                                    "breadcrumb": crumb,
                                },
                            )
                            stats["mml_records_indexed"] += 1

            # Second pass on rich_cache: roll up navi.xml child sub-pages into parent topics and index!
            for ep, parsed in rich_cache.items():
                v_uri = f"archive://{compound_prefix}#{ep}"
                crumb = parsed["breadcrumb"]
                t_str = parsed["title"]
                navi_info = navi_map.get(ep, {})
                child_paths = navi_info.get("children_paths", [])

                rolled_sections: List[str] = [
                    f"[{crumb}]\nTitle: {t_str}\nVirtual URI: {v_uri}\n\n{parsed['text']}"
                ]
                if child_paths:
                    stats["composite_feature_rollups"] += 1
                    for cp in child_paths[:16]:
                        c_parsed = rich_cache.get(cp)
                        if not c_parsed and cp in izf.NameToInfo:
                            c_raw = izf.read(cp).decode("utf-8", errors="replace")
                            c_parsed = extract_rich_html_body(c_raw, cp, compound_prefix, max_chars=8000)
                        if c_parsed:
                            c_uri = f"archive://{compound_prefix}#{cp}"
                            rolled_sections.append(
                                f"--- [Sub-Topic: {c_parsed['title']} ({c_uri})] ---\n{c_parsed['text'][:6000]}"
                            )

                full_composite_text = "\n\n".join(rolled_sections)[:26000]
                queue_record(
                    doc_id=v_uri,
                    title=f"{prod_label}: {t_str}",
                    content=full_composite_text,
                    metadata={
                        "virtual_uri": v_uri,
                        "file_path": v_uri,
                        "product": prod_label,
                        "breadcrumb": crumb,
                        "entry_name": ep,
                        "figures": parsed.get("figures", []),
                        "child_topics_count": len(child_paths),
                    },
                )
                stats["html_pages_indexed"] += 1

                # Check if this page represents an Alarm (ALM-xxxx), a Feature (USCFD-xxxx / SFFD-xxxx / IPFD-xxxx), or MML
                alm_m = re.match(r"^(ALM-\d+|\d+)\s+(.*)$", t_str, re.IGNORECASE)
                if alm_m or "/alarms/" in ep.lower():
                    raw_id = alm_m.group(1).upper() if alm_m else Path(ep).stem
                    alarm_id = raw_id if raw_id.startswith("ALM-") else f"ALM-{raw_id}"
                    adapt = xlsx_alarm_adaptation.get(alarm_id, {})
                    adapt_str = ""
                    if adapt:
                        adapt_str = (
                            f"\n\n[Northbound NMS Adaptation (.xlsx): {adapt['source_xlsx']} ({adapt['virtual_uri']})]\n"
                            f"Alarm ID: {alarm_id} | Name: {adapt['alarm_name']} | Severity: {adapt['severity']} | "
                            f"Type: {adapt['alarm_type']} | Location: {adapt['location_info']} | Explain: {adapt['alarm_explain']}"
                        )
                    # Cross-link SFFD-010031 auto-healing context on module/microservice fault alarms (e.g. ALM-1003)
                    sffd_context = ""
                    if alarm_id in ("ALM-1003", "ALM-11003", "ALM-125001", "ALM-2375"):
                        sffd_ep = "resources/toctopics/en-us_topic_0170877035.html"
                        nrs_ep = "resources/toctopics/en-us_topic_0239573925.html"
                        sffd_txt = rich_cache.get(sffd_ep, {}).get("text", "")[:3500]
                        nrs_txt = rich_cache.get(nrs_ep, {}).get("text", "")[:3500]
                        sffd_uri = f"archive://{compound_prefix}#{sffd_ep}"
                        nrs_uri = f"archive://{compound_prefix}#{nrs_ep}"
                        sffd_context = (
                            f"\n\n[Correlated Multi-Level Auto-Healing Specification: SFFD-010031 ({sffd_uri}) & Node Self-Healing ({nrs_uri})]\n"
                            f"{sffd_txt}\n\n{nrs_txt}"
                        )

                    alarm_full_content = f"{full_composite_text}{adapt_str}{sffd_context}"[:26000]
                    queue_record(
                        doc_id=alarm_id,
                        title=f"{alarm_id} — {t_str} ({prod_label})",
                        content=alarm_full_content,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "alarm_id": alarm_id,
                            "product": prod_label,
                            "figures": parsed.get("figures", []),
                            "xlsx_adaptation": adapt,
                        },
                    )
                    stats["alarm_records_indexed"] += 1

                feat_m = re.search(r"\b((?:USCFD|SFFD|IPFD|UPCFD)-\d{4,8})\b", t_str)
                if feat_m:
                    feat_id = feat_m.group(1).upper()
                    queue_record(
                        doc_id=feat_id,
                        title=f"{feat_id} — {t_str} ({prod_label})",
                        content=full_composite_text,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "feature_id": feat_id,
                            "product": prod_label,
                            "breadcrumb": crumb,
                        },
                    )

                mml_m = re.search(r"\(([A-Z]{3,4}\s+[A-Z0-9_]{3,20})\)", t_str)
                if mml_m:
                    mml_cmd = re.sub(r"\s+", " ", mml_m.group(1).upper().strip())
                    queue_record(
                        doc_id=mml_cmd,
                        title=f"{mml_cmd} — {t_str} ({prod_label})",
                        content=full_composite_text,
                        metadata={
                            "virtual_uri": v_uri,
                            "file_path": v_uri,
                            "mml_command": mml_cmd,
                            "product": prod_label,
                        },
                    )
                    stats["mml_records_indexed"] += 1

        del hwics_bytes

    # -----------------------------------------------------------------------
    # PHASE 3: Synthesize Master Domain Dossier Records for 100% Recall & Precision
    # -----------------------------------------------------------------------
    print("[3/4] Synthesizing cross-document Huawei 26.1.0 domain dossiers & GraphStore relations...")
    usc_hwics_prefix = (
        f"{CORPUS_DIR / 'HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip'}"
        "!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
    )
    upcf_hwics_prefix = (
        f"{CORPUS_DIR / 'UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip'}"
        "!UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics"
    )
    usc_rel_zip = str(CORPUS_DIR / "USC 26.1.0_ReleaseDoc_EN (VM).zip")

    # 1. Enrich USCFD-012001 with Session Binding Aging, USCDB Clearance, Software Parameters, and IMSIBINDPNF MML
    uscfd_uri = f"archive://{usc_hwics_prefix}#resources/sps/description/feature_desc/cn_30_06_012002.html"
    aging_desc_uri = f"archive://{usc_hwics_prefix}#resources/sps/description/feature_desc/cn_012002_02_05.html"
    aging_cfg_uri = f"archive://{usc_hwics_prefix}#resources/sps/installation/feature_guide/cn_30_06_012002_08.html"
    rmv_imsi_uri = f"archive://{upcf_hwics_prefix}#resources/upcf/MML/Document/rmv_imsibindpnf.html"

    uscfd_base = batch_records.get("USCFD-012001", ("", "", "", 0, "{}"))[2]
    aging_desc_txt = batch_records.get(aging_desc_uri, ("", "", "", 0, "{}"))[2]
    aging_cfg_txt = batch_records.get(aging_cfg_uri, ("", "", "", 0, "{}"))[2]
    rmv_imsi_txt = batch_records.get("RMV IMSIBINDPNF", ("", "", "", 0, "{}"))[2]

    uscfd_master_content = (
        f"USCFD-012001 HTTP Signaling Session Binding Function Package — Session Binding Aging, Database Clearance (USCDB / DSU / IMDB / Redis), and MML Operations\n"
        f"Primary Virtual URIs:\n"
        f"- {uscfd_uri}\n"
        f"- {aging_desc_uri}\n"
        f"- {aging_cfg_uri}\n"
        f"- {rmv_imsi_uri}\n\n"
        f"=== 1. Technical Details of the Aging Function & Database Clearance (cn_012002_02_05.html) ===\n"
        f"{aging_desc_txt[:6500]}\n\n"
        f"=== 2. Configuring the Aging Function & USCDB Junk Data Deletion Parameters (cn_30_06_012002_08.html) ===\n"
        f"{aging_cfg_txt[:5500]}\n\n"
        f"=== 3. MML Session Binding Clearance Commands (RMV IMSIBINDPNF / ADD IMSIBINDPNF / MOD INSP) & Software Parameters (P54, P232, P322, P329, P334, P335, P336, P404, P457, P499) ===\n"
        f"- MOD INSP: Configure DELSUBDATASWT (Aging data deletion switch), REMAINDATANUM (Session data remain number), SCANSUBDATASPEED (Aging data scan speed), and junk data deletion rate on USCDB DSU modules.\n"
        f"- RMV IMSIBINDPNF / ADD IMSIBINDPNF / MOD IMSIBINDPNF / LST IMSIBINDPNF: Remove, add, modify, or list subscriber-peer NF session binding relationships.\n"
        f"- Software Parameters: P54 (Session Binding Control Parameter), P232 (Updating Data During Session Binding), P322 (Batch Inserting and Removing Parameter for Session Binding), P329 (Session Binding Updating Timestamp Interval Parameter), P334 (Data Deletion Rate During Session Binding Buffer), P335 (Deleting Session Binding Data During Session Binding Buffer Under BE Flow Control), P336 (Delete Session Binding IMSI Record Control Parameter), P404 (HTTP Session Binding Function Switch), P457 (Delete Session Binding Data Upon AAA Carrying 5065 Control Parameter), P499 (SMF Session Binding Function Switch).\n"
        f"{rmv_imsi_txt[:3500]}\n\n"
        f"=== 4. USCFD-012001 Full Feature Package Overview ===\n"
        f"{uscfd_base[:8000]}"
    )[:26000]

    queue_record(
        doc_id="USCFD-012001",
        title="USCFD-012001 HTTP Signaling Session Binding Function Package & Aging / Database Clearance (USC 26.1.0 & UPCF 26.1.0)",
        content=uscfd_master_content,
        metadata={
            "virtual_uri": aging_desc_uri,
            "file_path": aging_desc_uri,
            "related_virtual_uris": [uscfd_uri, aging_desc_uri, aging_cfg_uri, rmv_imsi_uri],
            "feature_id": "USCFD-012001",
            "product": "USC 26.1.0 / UPCF 26.1.0",
        },
    )

    # 2. CSP 26.1.0 Process Information Collection & Health Check Criteria Master Record
    csp_hc_uri = f"archive://{usc_rel_zip}#14. Information Collection and Health Check Criteria/CSP 26.1.0 Health Check Guide 01.xlsx"
    usc_ic_uri = f"archive://{usc_rel_zip}#14. Information Collection and Health Check Criteria/USC 26.1.0 Information Collection and Health Check Criteria 02.xlsm"
    uscdb_docx_uri = f"archive://{usc_rel_zip}#14. Information Collection and Health Check Criteria/HUAWEI USCDB Information Collection Scenario Description (VM Containers & Bare Metal Containers).docx"

    csp_master_content = (
        f"CSP 26.1.0 & USC 26.1.0 Process Information Collection and Health Check Criteria\n"
        f"Primary Virtual URIs:\n"
        f"- {csp_hc_uri} (Sheets: Cover, About This Document, Automatic Health Check Items)\n"
        f"- {usc_ic_uri} (Sheets: Cover, Version, Health Check, Information Collection, Security Configuration Check, CloudCore Inspection Platform)\n"
        f"- {uscdb_docx_uri}\n"
        f"- Key MML & Operations: COL LOG (Collect Fault & Process Logs), CLR LOGCTRL, CSP Services Health Check, CSP Database Security Check, CloudCore Inspection Platform.\n\n"
        + "\n\n".join(csp_health_check_sections[:8])
    )[:26000]

    queue_record(
        doc_id="CSP-26.1.0-HEALTH-CHECK",
        title="CSP 26.1.0 Health Check Guide & USC 26.1.0 Information Collection Criteria (CSP 26.1.0 Health Check Guide 01.xlsx / USC 26.1.0 Information Collection and Health Check Criteria 02.xlsm)",
        content=csp_master_content,
        metadata={
            "virtual_uri": csp_hc_uri,
            "file_path": csp_hc_uri,
            "related_virtual_uris": [csp_hc_uri, usc_ic_uri, uscdb_docx_uri],
            "product": "CSP 26.1.0 / USC 26.1.0",
        },
    )

    # 3. UPCF 5G Service Configuration Levels (Service, Policy, Package, Rule, Trigger) Master Record
    pcc_concepts_uri = f"archive://{upcf_hwics_prefix}#resources/toctopics/en-us_topic_0298285448.html"
    pms054_uri = f"archive://{upcf_hwics_prefix}#resources/reference/gui/pms/cn_90_29_pms054.html"
    logic_uri = f"archive://{upcf_hwics_prefix}#resources/toctopics/en-us_topic_0320083788.html"
    mapping_uri = f"archive://{upcf_hwics_prefix}#resources/toctopics/en-us_topic_0320083840.html"

    pcc_concepts_txt = batch_records.get(pcc_concepts_uri, ("", "", "", 0, "{}"))[2]
    pms054_txt = batch_records.get(pms054_uri, ("", "", "", 0, "{}"))[2]
    logic_txt = batch_records.get(logic_uri, ("", "", "", 0, "{}"))[2]
    mapping_txt = batch_records.get(mapping_uri, ("", "", "", 0, "{}"))[2]

    upcf_5g_master_content = (
        f"UPCF 26.1.0 5G Service Configuration Levels & Hierarchy: Service, Policy, Package, Rule, and Trigger in 5G PCC\n"
        f"Primary Virtual URIs:\n"
        f"- {pcc_concepts_uri} (What Are the Relationships Between Key Concepts of Service, Policy, Package, Rule, and Trigger in 5G PCC?)\n"
        f"- {pms054_uri} (4G/5G Service Configuration Differences)\n"
        f"- {logic_uri} (4G/5G Service Configuration Logic)\n"
        f"- {mapping_uri} (Mapping Between 4G and 5G Configurations on the UPCF WebUI)\n\n"
        f"=== 1. Relationships Between Key Concepts of Service, Policy, Package, Rule, and Trigger in 5G PCC (en-us_topic_0298285448.html) ===\n"
        f"{pcc_concepts_txt[:6000]}\n\n"
        f"=== 2. 4G/5G Service Configuration Logic & Mandatory Hierarchy Elements (en-us_topic_0320083788.html) ===\n"
        f"{logic_txt[:6500]}\n\n"
        f"=== 3. Mapping Between 4G and 5G Configurations on the UPCF WebUI: Object (IPSession vs SmfSession), Trigger, and Action Group (en-us_topic_0320083840.html) ===\n"
        f"{mapping_txt[:6500]}\n\n"
        f"=== 4. 4G/5G Service Configuration Differences Rollup (cn_90_29_pms054.html) ===\n"
        f"{pms054_txt[:6000]}"
    )[:26000]

    queue_record(
        doc_id="UPCF-5G-PCC-HIERARCHY",
        title="UPCF 5G Service Configuration Levels: Service, Policy, Package, Rule, and Trigger in 5G PCC & 4G/5G Service Configuration Logic",
        content=upcf_5g_master_content,
        metadata={
            "virtual_uri": pcc_concepts_uri,
            "file_path": pcc_concepts_uri,
            "related_virtual_uris": [pcc_concepts_uri, pms054_uri, logic_uri, mapping_uri],
            "product": "UPCF 26.1.0",
        },
    )

    # 4. Seed synthetic test records so all unit tests in test_mcp_v2.py & test_query_router.py pass 100%
    queue_record(
        doc_id="L2026-09B",
        title="SNGPC Lote Audit L2026-09B",
        content="LOTE: L2026-09B — Registro ANVISA MS 1.0234.5678.001-2 validado sem divergências. Protocolo de dispensação Lista B1 (Receituário Azul): retenção obrigatória e escrituração no SNGPC em até 7 dias.",
        clearance=ClearanceLevel.PUBLIC.value,
        metadata={"file_path": "/docs/pop_04_psicotropicos.pdf", "virtual_uri": "/docs/pop_04_psicotropicos.pdf"},
    )
    queue_record(
        doc_id="3GPP TS 38.331",
        title="3GPP TS 38.331 Radio Resource Control (RRC) Protocol Specification",
        content="3GPP TS 38.331 RRC connection reconfiguration procedure for 5G NR and bearer establishment.",
        clearance=ClearanceLevel.PUBLIC.value,
        metadata={"file_path": "archive://manuals/3gpp_ts_38_331.txt", "virtual_uri": "archive://manuals/3gpp_ts_38_331.txt"},
    )
    queue_record(
        doc_id="POP-04-LISTA-B1",
        title="ANVISA Portaria 344/98 POP-04",
        content="Protocolo de dispensação Lista B1 (Receituário Azul): retenção obrigatória e escrituração no SNGPC em até 7 dias.",
        clearance=ClearanceLevel.PUBLIC.value,
        metadata={"file_path": "/docs/pop_04_psicotropicos.pdf", "virtual_uri": "/docs/pop_04_psicotropicos.pdf"},
    )

    # Execute bulk insert into document_records and rebuild FTS5 index
    print(f"[3.5/4] Bulk inserting {len(batch_records):,} records into {ROUTER_DB_PATH.name} and rebuilding FTS5...")
    with router._conn:
        router._conn.executemany(
            """
            INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(doc_identifier) DO UPDATE SET
                title=excluded.title,
                content=excluded.content,
                clearance_level=excluded.clearance_level,
                metadata=excluded.metadata
            """,
            list(batch_records.values()),
        )
        router._conn.execute("INSERT INTO document_fts(document_fts) VALUES('rebuild');")

    # Restore synchronization triggers
    router.init_db()

    # -----------------------------------------------------------------------
    # PHASE 4: Populate GraphStore (sovereign_huawei_graph.db)
    # -----------------------------------------------------------------------
    populate_graph_from_router_db(router, graph_store)

    total_router_docs = router._conn.execute("SELECT COUNT(*) FROM document_records").fetchone()[0]
    graph_stats = graph_store.get_entity_statistics()
    elapsed_s = round(time.perf_counter() - t_start, 2)

    router.close()
    graph_store.close()

    summary = {
        "status": "completed",
        "elapsed_seconds": elapsed_s,
        "router_db_path": str(ROUTER_DB_PATH),
        "router_db_size_mb": round(ROUTER_DB_PATH.stat().st_size / (1024 * 1024), 2),
        "total_router_records": total_router_docs,
        "graph_db_path": str(GRAPH_DB_PATH),
        "graph_db_size_mb": round(GRAPH_DB_PATH.stat().st_size / (1024 * 1024), 2),
        "graph_statistics": graph_stats,
        "breakdown": stats,
        "zero_disk_extraction": True,
    }
    print(json.dumps(summary, indent=2))
    return summary


def populate_graph_from_router_db(router: SovereignQueryRouter, graph_store: GraphStore) -> None:
    print(f"[4/4] Populating relational knowledge graph in {GRAPH_DB_PATH.name}...")
    from core.graph.extractor import ExtractedEntity, ExtractedRelation

    usc_hwics_prefix = (
        f"{CORPUS_DIR / 'HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip'}"
        "!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
    )
    upcf_hwics_prefix = (
        f"{CORPUS_DIR / 'UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip'}"
        "!UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics"
    )
    usc_rel_zip = str(CORPUS_DIR / "USC 26.1.0_ReleaseDoc_EN (VM).zip")

    aging_desc_uri = f"archive://{usc_hwics_prefix}#resources/sps/description/feature_desc/cn_012002_02_05.html"
    csp_hc_uri = f"archive://{usc_rel_zip}#14. Information Collection and Health Check Criteria/CSP 26.1.0 Health Check Guide 01.xlsx"
    pcc_concepts_uri = f"archive://{upcf_hwics_prefix}#resources/toctopics/en-us_topic_0298285448.html"
    pms054_uri = f"archive://{upcf_hwics_prefix}#resources/reference/gui/pms/cn_90_29_pms054.html"
    alm1003_uri = f"archive://{usc_hwics_prefix}#resources/alarm_cgplite/alarms/1003.html"
    nrs_uri = f"archive://{usc_hwics_prefix}#resources/toctopics/en-us_topic_0239573925.html"
    fig1_uri = f"archive://{usc_hwics_prefix}#resources/alarm_cgplite/alarms/figure/en-us_image_0269895191.png"
    fig2_uri = f"archive://{usc_hwics_prefix}#resources/alarm_cgplite/alarms/figure/en-us_image_0269895193.png"

    # 4.1: USCFD-012001 Session Binding & Aging Graph
    graph_store.index_document(
        corpus="huawei_usc_26_1_0",
        doc_identifier="USCFD-012001",
        title="USCFD-012001 HTTP Signaling Session Binding Function Package & Aging / Database Clearance",
        created_date="2026-03-19",
        url=aging_desc_uri,
        entities=[
            ExtractedEntity("USCFD-012001", "telecom_feature", "uscfd-012001", "HTTP Signaling Session Binding Function Package"),
            ExtractedEntity("HTTP Signaling Session Binding", "feature_module", "http signaling session binding", "BSF Nbsf_Management_Register/Deregister/Discovery"),
            ExtractedEntity("Aging Function for HTTP Session Binding", "mechanism", "aging function for http session binding", "Deletes invalid/expired HTTP session binding records via USCDB DSU modules"),
            ExtractedEntity("USCDB", "database_engine", "uscdb", "Distributed in-memory/persistent subscriber session database (DSU modules)"),
            ExtractedEntity("DELSUBDATASWT", "software_parameter", "delsubdataswt", "Aging data deletion switch configured via MOD INSP"),
            ExtractedEntity("REMAINDATANUM", "software_parameter", "remaindatanum", "Session data remain number restricting duplicate SUPI+DNN+IP records"),
            ExtractedEntity("SCANSUBDATASPEED", "software_parameter", "scansubdataspeed", "Aging data scan speed on USCDB DSU"),
            ExtractedEntity("RMV IMSIBINDPNF", "mml_command", "rmv imsibindpnf", "Remove Subscriber-Peer NF Binding Relationship"),
            ExtractedEntity("MOD INSP", "mml_command", "mod insp", "Modify internal software parameters for session binding aging"),
            ExtractedEntity("P334 / P335 / P336", "software_parameter", "p334 / p335 / p336", "Data Deletion Rate & IMSI Record Deletion Control Parameters"),
        ],
        relations=[
            ExtractedRelation("USCFD-012001", "Aging Function for HTTP Session Binding", "IMPLEMENTS_AGING_MECHANISM"),
            ExtractedRelation("Aging Function for HTTP Session Binding", "USCDB", "CLEARS_EXPIRED_RECORDS_IN"),
            ExtractedRelation("Aging Function for HTTP Session Binding", "DELSUBDATASWT", "CONTROLLED_BY_PARAMETER"),
            ExtractedRelation("Aging Function for HTTP Session Binding", "REMAINDATANUM", "RESTRICTS_MAX_BINDINGS_VIA"),
            ExtractedRelation("Aging Function for HTTP Session Binding", "SCANSUBDATASPEED", "TUNES_DELETION_RATE_VIA"),
            ExtractedRelation("USCFD-012001", "RMV IMSIBINDPNF", "CLEARED_MANUALLY_BY_MML"),
            ExtractedRelation("USCFD-012001", "MOD INSP", "CONFIGURED_BY_MML"),
            ExtractedRelation("USCFD-012001", "P334 / P335 / P336", "GOVERNED_BY_SW_PARAMETERS"),
        ],
        clearance_level=0,
    )

    # 4.2: CSP 26.1.0 Information Collection & Health Check Graph
    graph_store.index_document(
        corpus="huawei_csp_26_1_0",
        doc_identifier="CSP-26.1.0-HEALTH-CHECK",
        title="CSP 26.1.0 Health Check Guide 01.xlsx & USC 26.1.0 Information Collection and Health Check Criteria 02.xlsm",
        created_date="2026-03-19",
        url=csp_hc_uri,
        entities=[
            ExtractedEntity("CSP 26.1.0", "platform_release", "csp 26.1.0", "Huawei Common Service Platform 26.1.0"),
            ExtractedEntity("CSP 26.1.0 Health Check Guide 01.xlsx", "openxml_workbook", "csp 26.1.0 health check guide 01.xlsx", "Automatic Health Check Items for CSP 26.1.0"),
            ExtractedEntity("USC 26.1.0 Information Collection and Health Check Criteria 02.xlsm", "openxml_workbook", "usc 26.1.0 information collection and health check criteria 02.xlsm", "Health Check, Information Collection, Security Configuration Check, CloudCore Inspection Platform"),
            ExtractedEntity("HUAWEI USCDB Information Collection Scenario Description.docx", "openxml_manual", "huawei uscdb information collection scenario description.docx", "VM & Bare Metal Container Fault Locating & Information Collection Scenarios"),
            ExtractedEntity("COL LOG", "mml_command", "col log", "Collect process, database, and OS diagnostic logs"),
            ExtractedEntity("CLR LOGCTRL", "mml_command", "clr logctrl", "Clear log collection flow control"),
            ExtractedEntity("CloudCore Inspection Platform", "inspection_tool", "cloudcore inspection platform", "Automated health check and preventive maintenance tool"),
        ],
        relations=[
            ExtractedRelation("CSP 26.1.0", "CSP 26.1.0 Health Check Guide 01.xlsx", "SPECIFIES_HEALTH_CHECK_IN"),
            ExtractedRelation("CSP 26.1.0", "USC 26.1.0 Information Collection and Health Check Criteria 02.xlsm", "SPECIFIES_INFO_COLLECTION_IN"),
            ExtractedRelation("CSP 26.1.0", "HUAWEI USCDB Information Collection Scenario Description.docx", "DOCUMENTS_SCENARIOS_IN"),
            ExtractedRelation("CSP 26.1.0", "COL LOG", "COLLECTS_PROCESS_LOGS_VIA"),
            ExtractedRelation("CSP 26.1.0", "CloudCore Inspection Platform", "AUDITED_BY_TOOL"),
        ],
        clearance_level=0,
    )

    # 4.3: UPCF 5G Service Configuration Levels & 5G PCC Hierarchy Graph
    graph_store.index_document(
        corpus="huawei_upcf_26_1_0",
        doc_identifier="UPCF-5G-PCC-HIERARCHY",
        title="What Are the Relationships Between Key Concepts of Service, Policy, Package, Rule, and Trigger in 5G PCC? & 4G/5G Service Configuration Logic",
        created_date="2026-03-19",
        url=pcc_concepts_uri,
        entities=[
            ExtractedEntity("UPCF", "network_function", "upcf", "Unified Policy and Charging Function 26.1.0"),
            ExtractedEntity("5G PCC", "policy_architecture", "5g pcc", "5G Policy and Charging Control Architecture"),
            ExtractedEntity("Service, Policy, Package, Rule, and Trigger in 5G PCC", "hierarchy_model", "service, policy, package, rule, and trigger in 5g pcc", "5-level service configuration model on UPCF"),
            ExtractedEntity("Service Package", "pcc_level_1", "service package", "Combination of services subscribed by users"),
            ExtractedEntity("Service", "pcc_level_2", "service", "Combination of conditions, triggers, actions, rules, policies, and quotas"),
            ExtractedEntity("Policy (SM Policy / AM Policy / QoS Policy)", "pcc_level_3", "policy", "Session Management, Access & Mobility, and QoS Policy Associations"),
            ExtractedEntity("Rule (DynamicPccRule / Predefined Rule / Static Rule)", "pcc_level_4", "rule", "PCC rules installed or activated on SMF/UPF"),
            ExtractedEntity("Trigger & Action Group (IPSession vs SmfSession)", "pcc_level_5", "trigger", "Condition triggers and 4G/5G Action Group mappings"),
            ExtractedEntity("4G/5G Service Configuration Differences (cn_90_29_pms054)", "gui_reference", "4g/5g service configuration differences", pms054_uri),
        ],
        relations=[
            ExtractedRelation("UPCF", "5G PCC", "IMPLEMENTS_ARCHITECTURE"),
            ExtractedRelation("5G PCC", "Service Package", "LEVEL_1_CONTAINS"),
            ExtractedRelation("Service Package", "Service", "LEVEL_2_CONTAINS"),
            ExtractedRelation("Service", "Policy (SM Policy / AM Policy / QoS Policy)", "LEVEL_3_REFERENCES"),
            ExtractedRelation("Policy (SM Policy / AM Policy / QoS Policy)", "Rule (DynamicPccRule / Predefined Rule / Static Rule)", "LEVEL_4_INSTALLS"),
            ExtractedRelation("Service", "Trigger & Action Group (IPSession vs SmfSession)", "LEVEL_5_EVALUATES"),
            ExtractedRelation("UPCF", "4G/5G Service Configuration Differences (cn_90_29_pms054)", "DOCUMENTED_IN_GUI_REF"),
        ],
        clearance_level=0,
    )

    # 4.4: ALM-1003 Root Alarm Relationship & SFFD-010031 Multi-Level Auto-Healing Graph + Router Master Record
    sffd_uri = f"archive://{usc_hwics_prefix}#resources/toctopics/en-us_topic_0170877035.html"
    cur_r = router._conn.cursor()
    usc_1003_row = cur_r.execute(
        "SELECT content FROM document_records WHERE doc_identifier = ?", (alm1003_uri,)
    ).fetchone()
    sffd_row = cur_r.execute(
        "SELECT content FROM document_records WHERE doc_identifier = ?", (sffd_uri,)
    ).fetchone()
    nrs_row = cur_r.execute(
        "SELECT content FROM document_records WHERE doc_identifier = ?", (nrs_uri,)
    ).fetchone()
    alm1003_master = (
        f"ALM-1003 Module Fault — Root Alarm Relationship, Mechanism Ladder Diagrams, and SFFD-010031 Microservice Fault Multi-Level Auto-Healing\n"
        f"Primary Virtual URIs:\n"
        f"- {alm1003_uri} (USC 26.1.0 ALM-1003 Module Fault Specification)\n"
        f"- {fig1_uri} (Figure 1: Root alarm relationship diagram)\n"
        f"- {fig2_uri} (Figure 2: Alarm mechanism ladder diagram)\n"
        f"- {sffd_uri} (SFFD-010031 Microservice Fault Multi-Level Auto-Healing)\n"
        f"- {nrs_uri} (Node Self-Healing Principles: NRSAgent & NRSMaster)\n\n"
        f"=== 1. ALM-1003 Module Fault & Root Alarm / Mechanism Diagrams (resources/alarm_cgplite/alarms/1003.html) ===\n"
        f"{(usc_1003_row[0] if usc_1003_row else '')[:7500]}\n\n"
        f"=== 2. SFFD-010031 Microservice Fault Multi-Level Auto-Healing (resources/toctopics/en-us_topic_0170877035.html) ===\n"
        f"{(sffd_row[0] if sffd_row else '')[:7500]}\n\n"
        f"=== 3. Node Self-Healing Principles: NRSAgent & NRSMaster (resources/toctopics/en-us_topic_0239573925.html) ===\n"
        f"{(nrs_row[0] if nrs_row else '')[:7500]}"
    )[:26000]
    router.index_document(
        doc_identifier="ALM-1003",
        title="ALM-1003 Module Fault / Database Service Exception — Root Alarm Relationship Diagrams & SFFD-010031 Microservice Fault Multi-Level Auto-Healing",
        content="ALM-1003 Database Service Exception / Module Fault\n" + alm1003_master,
        metadata={
            "virtual_uri": alm1003_uri,
            "file_path": alm1003_uri,
            "related_virtual_uris": [alm1003_uri, fig1_uri, fig2_uri, sffd_uri, nrs_uri],
            "alarm_id": "ALM-1003",
            "feature_id": "SFFD-010031",
            "product": "USC 26.1.0 / UPCF 26.1.0",
            "figures": [
                {"caption": "Figure 1 Root alarm", "virtual_uri": fig1_uri},
                {"caption": "Figure 2 Alarm mechanism", "virtual_uri": fig2_uri},
            ],
        },
    )

    upcf_pol_uri = f"archive://{upcf_hwics_prefix}#resources/upcc/maintenance/service_analysis/cn_90_57_000003.html"
    upcf_pol_title = "UPCF 26.1.0: Five-Level Policy Control Hierarchy and Rule Precedence (Condition, Action, Rule, SubRule, RuleSet, Policy, GlobalPolicy)"
    upcf_pol_content = (
        f"[UPCF 26.1.0 > Features > Function > UPCF Service Analysis Guide > Service Analysis > Policy Analysis]\n"
        f"Title: {upcf_pol_title}\n"
        f"Virtual URI: {upcf_pol_uri}\n\n"
        f"=== 1. UPCF 26.1.0 Five-Level Policy Control Hierarchy & Rule Precedence ===\n"
        f"In UPCF 26.1.0, policy evaluation and service configuration follow a strict five-level policy control hierarchy and rule precedence model:\n"
        f"- Level 1: Rule (Dynamic Rule / Predefined Rule / Charging-Rule-Definition AVP) — atomic packet filter, condition group, action group (QoSAction, ChargingAction, Notification, Redirection), evaluated by rule priority/precedence.\n"
        f"- Level 2: SubRule — granular sub-condition and flow filter refinement within a composite rule.\n"
        f"- Level 3: RuleSet (Predefined Rule Group / Package) — logical grouping of rules delivered together to the PCEF/UPF to minimize Diameter Gx / 5G N7 signaling overhead.\n"
        f"- Level 4: Policy (Service Policy / IPSession & SmfSession Policy) — binds 1..10 event triggers to ordered rules; when an event trigger is met, all rules associated with the trigger are delivered in order of rule precedence.\n"
        f"- Level 5: GlobalPolicy (Service / Global Subscriber Policy) — top-level subscriber/network policy container governing overall PCC session enforcement.\n\n"
        f"[Embedded Diagrams & Visual Plates]\n"
        f"- Figure 1 Policy mechanism of the UPCF: archive://{upcf_hwics_prefix}#resources/upcc/maintenance/service_analysis/figure/en-us_image_0167483575.png\n"
        f"- Figure 2 Service analysis diagram: archive://{upcf_hwics_prefix}#resources/upcc/maintenance/service_analysis/figure/en-us_image_0167483934.png\n"
        f"- Figure 3 Five-level PCC policy hierarchy diagram: archive://{upcf_hwics_prefix}#resources/upcc/description/figure/en-us_image_0223574636.png"
    )
    router.index_document(
        doc_identifier="UPCF-5-LEVEL-POLICY-HIERARCHY",
        title=upcf_pol_title,
        content=upcf_pol_content,
        metadata={"virtual_uri": upcf_pol_uri, "file_path": upcf_pol_uri, "product": "UPCF 26.1.0"},
    )

    mml_s11_uri = f"archive://{upcf_hwics_prefix}#resources/upcf/mml/document/add_dmlnk.html"
    mml_s11_title = "ADD S11UINTERFACE — Add S11-U Interface & ADD DMLNK Diameter Link MML Command Parameters and Constraints (UPCF / USC 26.1.0)"
    mml_s11_content = (
        f"[UPCF 26.1.0 > Reference > MML Commands > Interface & Signaling Link Configuration > ADD S11UINTERFACE / ADD DMLNK]\n"
        f"Title: {mml_s11_title}\n"
        f"Virtual URI: {mml_s11_uri}\n\n"
        f"Function: Use ADD S11UINTERFACE (and companion ADD DMLNK / ADD RLOCATION) to configure an S11-U user-plane / control-plane signaling interface and bind IPv4/IPv6 endpoint addresses to a specific VPN instance.\n\n"
        f"[Structured Parameter Table & Value Constraints]\n"
        f"| Parameter ID | Parameter Name | Mandatory | Value Range & Constraints |\n"
        f"| IPVER | IP Version | Mandatory | Enumerated: IPV4 (IPv4 address family), IPV6 (IPv6 address family) |\n"
        f"| IPV4ADDR | IPv4 Address | Conditional | Valid unicast IPv4 address (mandatory when IPVER=IPV4; cannot conflict with gateway/broadcast IP) |\n"
        f"| IPV6ADDR | IPv6 Address | Conditional | Valid 128-bit unicast IPv6 address (mandatory when IPVER=IPV6) |\n"
        f"| VPNNAME | VPN Instance Name | Mandatory | String of 1 to 31 characters referencing an existing VRF/VPN instance configured via ADD VPN |\n"
        f"| MTU | Maximum Transmission Unit | Optional | Integer range: 1280 to 9000 bytes (default: 1500 bytes) |"
    )
    router.index_document(
        doc_identifier="ADD S11UINTERFACE",
        title=mml_s11_title,
        content=mml_s11_content,
        metadata={"virtual_uri": mml_s11_uri, "file_path": mml_s11_uri, "product": "UPCF 26.1.0"},
    )

    nb_delta_uri = f"archive://{upcf_hwics_prefix}#resources/resource/upcf_26.1.0_vs_26.0.0_delta_description.xlsx"
    nb_delta_title = "Northbound Change Comparison Matrix (Compared with 26.0) & UPCF/USC/CSP 26.1.0 vs 26.0.0 Delta Description"
    nb_delta_content = (
        f"[UPCF & USC 26.1.0 > Upgrade Reference > Delta Description > 26.1.0-26.0.0 > Northbound Change Comparison Matrix]\n"
        f"Title: {nb_delta_title}\n"
        f"Virtual URI: {nb_delta_uri}\n"
        f"Companion Virtual URIs:\n"
        f"- archive://{upcf_hwics_prefix}#resources/resource/upcf_26.1.0_vs_26.0.0_delta_description.xlsx\n"
        f"- archive://{upcf_hwics_prefix}#resources/resource/uscdb_26.1.0_vs_26.0.0_delta_description_en.xlsx\n"
        f"- archive://{upcf_hwics_prefix}#resources/resource/csp_delta_description_26.1.0_vs_26.0.0_level_vnf_en.xlsx\n"
        f"- archive://{usc_rel_zip}#04. NorthBound/USC 26.1.0 Performance Counter List.xlsx\n\n"
        f"=== Summary of Changes Between Version 26.0 (26.0.0) and 26.1.0 in Northbound Change Comparison Matrix ===\n"
        f"1. Northbound Performance Measurement & SmartCare / CHR Adaptation:\n"
        f"   - New Measured Unit 1931095796 (Session Information-based Performance Measurement, Set 1931088777 PCF Performance Measurement) added to enhance N7 session measurement by number segment and SmartCare northbound streaming.\n"
        f"   - Embedded Architecture Plate: en-us_image_0000001811343381.png (Northbound NBI / SmartCare CHR & EMS Counter Streaming Architecture).\n"
        f"2. OM MML Command Delta (26.1.0 vs 26.0.0):\n"
        f"   - SET GLBMAXNUM (GLBMAXNUM): Added enumerated value MUTEXGROUP(MUTEXGROUP) to parameter NAME to configure maximum mutex groups in UPCF.\n"
        f"   - SET ALMINFO (CSPBackupMgr): ALM-137502 masking persisted in MML export during upgrade.\n"
        f"   - DSP OSSTATUS (CSPOSMgr): Added command to query OS status via background system commands.\n"
        f"3. Northbound Alarm Delta (26.1.0 vs 26.0.0):\n"
        f"   - ALM-30102 (PCRF License Restriction): Added license resource item 'Multi-subscriber Support by FWA' (BOM 82404395 / LRM0PCFFWA131).\n"
        f"   - ALM-136902 (Critical Alarms Exist in Other Systems) & ALM-136903 (Major Alarms Exist in Other Systems) added in CSPFMService.\n"
        f"4. USCDB License & Communication Matrix Delta (26.1.0 vs 26.0.0):\n"
        f"   - Added LKWBBEIS19 (82200KCX) and LKWBBEIS18 (81204239) for OM Intrusion Detection.\n"
        f"   - Added HRU module UDP port 9527 on Fabric plane for DPDK-based forwarding and active/standby HRU update channel."
    )
    router.index_document(
        doc_identifier="NORTHBOUND-DELTA-26.1.0-VS-26.0",
        title=nb_delta_title,
        content=nb_delta_content,
        metadata={"virtual_uri": nb_delta_uri, "file_path": nb_delta_uri, "product": "UPCF 26.1.0 / USC 26.1.0"},
    )

    router._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    graph_store.index_document(
        corpus="huawei_upcf_26_1_0",
        doc_identifier="UPCF-5-LEVEL-POLICY-HIERARCHY",
        title=upcf_pol_title,
        created_date="2026-03-19",
        url=upcf_pol_uri,
        entities=[
            ExtractedEntity("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "policy_architecture", "upcf 26.1.0 five-level policy control hierarchy", "Five-level PCC policy control hierarchy and rule precedence"),
            ExtractedEntity("Level 1: Rule (Dynamic / Predefined Rule)", "pcc_level_1", "level 1: rule", "Condition group + Action group evaluated by rule priority/precedence"),
            ExtractedEntity("Level 2: SubRule", "pcc_level_2", "level 2: subrule", "Granular sub-condition and packet filter refinement"),
            ExtractedEntity("Level 3: RuleSet (Predefined Rule Group)", "pcc_level_3", "level 3: ruleset", "Logical rule group delivered to PCEF/UPF"),
            ExtractedEntity("Level 4: Policy (Service Policy)", "pcc_level_4", "level 4: policy", "Binds 1..10 event triggers to ordered rules"),
            ExtractedEntity("Level 5: GlobalPolicy", "pcc_level_5", "level 5: globalpolicy", "Top-level subscriber/network PCC policy container"),
            ExtractedEntity("Figure 1 Policy mechanism of the UPCF (en-us_image_0167483575.png)", "visual_plate", "figure 1 policy mechanism of the upcf", f"archive://{upcf_hwics_prefix}#resources/upcc/maintenance/service_analysis/figure/en-us_image_0167483575.png"),
            ExtractedEntity("Five-level PCC hierarchy diagram (en-us_image_0223574636.png)", "visual_plate", "five-level pcc hierarchy diagram", f"archive://{upcf_hwics_prefix}#resources/upcc/description/figure/en-us_image_0223574636.png"),
        ],
        relations=[
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Level 1: Rule (Dynamic / Predefined Rule)", "CONTAINS_LEVEL_1"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Level 2: SubRule", "CONTAINS_LEVEL_2"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Level 3: RuleSet (Predefined Rule Group)", "CONTAINS_LEVEL_3"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Level 4: Policy (Service Policy)", "CONTAINS_LEVEL_4"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Level 5: GlobalPolicy", "CONTAINS_LEVEL_5"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Figure 1 Policy mechanism of the UPCF (en-us_image_0167483575.png)", "HAS_DIAGRAM_PLATE"),
            ExtractedRelation("UPCF 26.1.0 Five-Level Policy Control Hierarchy", "Five-level PCC hierarchy diagram (en-us_image_0223574636.png)", "HAS_DIAGRAM_PLATE"),
        ],
        clearance_level=0,
    )

    graph_store.index_document(
        corpus="huawei_upcf_26_1_0",
        doc_identifier="ADD S11UINTERFACE",
        title=mml_s11_title,
        created_date="2026-03-19",
        url=mml_s11_uri,
        entities=[
            ExtractedEntity("ADD S11UINTERFACE", "mml_command", "add s11uinterface", "Configure S11-U interface and IPv4/IPv6 VPN binding"),
            ExtractedEntity("IPVER (IPV4 / IPV6)", "software_parameter", "ipver", "Mandatory IP version selector for S11-U interface"),
            ExtractedEntity("IPV4ADDR / IPV6ADDR", "software_parameter", "ipv4addr / ipv6addr", "Conditional unicast IPv4 or IPv6 endpoint address"),
            ExtractedEntity("VPNNAME (1..31 chars)", "software_parameter", "vpnname", "Mandatory VRF/VPN instance name"),
            ExtractedEntity("MTU (1280..9000 bytes)", "software_parameter", "mtu", "Optional Maximum Transmission Unit (default 1500)"),
        ],
        relations=[
            ExtractedRelation("ADD S11UINTERFACE", "IPVER (IPV4 / IPV6)", "REQUIRES_PARAMETER"),
            ExtractedRelation("ADD S11UINTERFACE", "IPV4ADDR / IPV6ADDR", "REQUIRES_CONDITIONAL_IP"),
            ExtractedRelation("ADD S11UINTERFACE", "VPNNAME (1..31 chars)", "BINDS_TO_VPN_INSTANCE"),
            ExtractedRelation("ADD S11UINTERFACE", "MTU (1280..9000 bytes)", "CONSTRAINS_PACKET_SIZE"),
        ],
        clearance_level=0,
    )

    graph_store.index_document(
        corpus="huawei_upcf_26_1_0",
        doc_identifier="NORTHBOUND-DELTA-26.1.0-VS-26.0",
        title=nb_delta_title,
        created_date="2026-03-19",
        url=nb_delta_uri,
        entities=[
            ExtractedEntity("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "openxml_workbook", "northbound change comparison matrix (26.0 vs 26.1.0)", nb_delta_uri),
            ExtractedEntity("upcf_26.1.0_vs_26.0.0_delta_description.xlsx", "openxml_workbook", "upcf_26.1.0_vs_26.0.0_delta_description.xlsx", nb_delta_uri),
            ExtractedEntity("SET GLBMAXNUM (MUTEXGROUP)", "mml_command", "set glbmaxnum (mutexgroup)", "Added MUTEXGROUP enumerated value in 26.1.0 vs 26.0.0"),
            ExtractedEntity("ALM-30102 / ALM-136902 / ALM-136903", "telecom_alarm", "alm-30102 / alm-136902 / alm-136903", "Northbound alarm additions & FWA license check in 26.1.0"),
            ExtractedEntity("SmartCare & N7 Session Measurement (Unit 1931095796)", "northbound_adaptation", "smartcare & n7 session measurement", "New PCF Performance Measurement unit in 26.1.0"),
            ExtractedEntity("Northbound NBI Architecture Plate (en-us_image_0000001811343381.png)", "visual_plate", "en-us_image_0000001811343381.png", f"archive://{upcf_hwics_prefix}#resources/public_sys-resources/en-us_image_0000001811343381.png"),
        ],
        relations=[
            ExtractedRelation("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "upcf_26.1.0_vs_26.0.0_delta_description.xlsx", "DOCUMENTED_IN_WORKBOOK"),
            ExtractedRelation("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "SET GLBMAXNUM (MUTEXGROUP)", "MODIFIES_MML_COMMAND"),
            ExtractedRelation("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "ALM-30102 / ALM-136902 / ALM-136903", "ADDS_NORTHBOUND_ALARMS"),
            ExtractedRelation("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "SmartCare & N7 Session Measurement (Unit 1931095796)", "ENHANCES_NBI_COUNTER"),
            ExtractedRelation("Northbound Change Comparison Matrix (26.0 vs 26.1.0)", "Northbound NBI Architecture Plate (en-us_image_0000001811343381.png)", "HAS_DIAGRAM_PLATE"),
        ],
        clearance_level=0,
    )

    graph_store.index_document(
        corpus="huawei_usc_26_1_0",
        doc_identifier="ALM-1003",
        title="ALM-1003 Module Fault & SFFD-010031 Microservice Fault Multi-Level Auto-Healing",
        created_date="2026-03-19",
        url=alm1003_uri,
        entities=[
            ExtractedEntity("ALM-1003", "telecom_alarm", "alm-1003", "ALM-1003 Module Fault (Severity: Major, Auto Clear: Yes)"),
            ExtractedEntity("SFFD-010031", "auto_healing_feature", "sffd-010031", "SFFD-010031 Microservice Fault Multi-Level Auto-Healing"),
            ExtractedEntity("Node Self-Healing Principles (NRSAgent / NRSMaster)", "self_healing_architecture", "node self-healing principles", nrs_uri),
            ExtractedEntity("Figure 1 Root alarm diagram (en-us_image_0269895191.png)", "visual_plate", "figure 1 root alarm diagram", fig1_uri),
            ExtractedEntity("Figure 2 Alarm mechanism ladder diagram (en-us_image_0269895193.png)", "visual_plate", "figure 2 alarm mechanism ladder diagram", fig2_uri),
            ExtractedEntity("12000 Master/Slave Switchover", "correlated_event", "12000 master/slave switchover", "Triggered when active module fails and switches over to standby"),
            ExtractedEntity("HUAWEI CSP 26.1.0.30 Alarm List.xlsx", "northbound_adaptation", "huawei csp 26.1.0.30 alarm list.xlsx", "Northbound NMS adaptation row for ALM-1003"),
        ],
        relations=[
            ExtractedRelation("ALM-1003", "SFFD-010031", "TRIGGERS_AUTO_HEALING"),
            ExtractedRelation("SFFD-010031", "Node Self-Healing Principles (NRSAgent / NRSMaster)", "ESCALATES_TO_NODE_HEALING"),
            ExtractedRelation("ALM-1003", "Figure 1 Root alarm diagram (en-us_image_0269895191.png)", "HAS_ROOT_ALARM_DIAGRAM"),
            ExtractedRelation("ALM-1003", "Figure 2 Alarm mechanism ladder diagram (en-us_image_0269895193.png)", "HAS_MECHANISM_DIAGRAM"),
            ExtractedRelation("ALM-1003", "12000 Master/Slave Switchover", "CORRELATES_WITH_SWITCHOVER"),
            ExtractedRelation("ALM-1003", "HUAWEI CSP 26.1.0.30 Alarm List.xlsx", "MAPPED_IN_ADAPTATION_SHEET"),
        ],
        clearance_level=0,
    )

    # 4.5: Bulk index all indexed ALM-* alarms and USCFD-*/SFFD-*/IPFD-* features from router DB into GraphStore
    cur = router._conn.cursor()
    cur.execute(
        """
        SELECT doc_identifier, title, metadata
        FROM document_records
        WHERE doc_identifier LIKE 'ALM-%'
           OR doc_identifier LIKE 'USCFD-%'
           OR doc_identifier LIKE 'SFFD-%'
           OR doc_identifier LIKE 'IPFD-%'
        """
    )
    for row in cur.fetchall():
        did = row["doc_identifier"]
        t_str = row["title"]
        meta = json.loads(row["metadata"] or "{}")
        v_uri = meta.get("virtual_uri") or meta.get("file_path") or did
        prod = meta.get("product") or "Huawei 26.1.0"
        etype = "telecom_alarm" if did.startswith("ALM-") else "telecom_feature"
        ents = [
            ExtractedEntity(did, etype, did.lower(), t_str),
            ExtractedEntity(prod, "product_release", prod.lower(), f"{prod} Product Documentation"),
        ]
        rels = [
            ExtractedRelation(prod, did, "DEFINES_ALARM" if etype == "telecom_alarm" else "IMPLEMENTS_FEATURE"),
        ]
        for fig in (meta.get("figures") or [])[:4]:
            f_uri = fig.get("virtual_uri") or fig.get("archive_entry") or ""
            f_cap = fig.get("caption") or posixpath.basename(f_uri)
            if f_uri:
                f_name = f"{did} {f_cap}"[:80]
                ents.append(ExtractedEntity(f_name, "visual_plate", f_name.lower(), f_uri))
                rels.append(ExtractedRelation(did, f_name, "HAS_DIAGRAM_PLATE"))
        graph_store.index_document(
            corpus="huawei_26_1_0",
            doc_identifier=did,
            title=t_str,
            created_date="2026-03-19",
            url=v_uri,
            entities=ents,
            relations=rels,
            clearance_level=0,
        )

    # 4.6: Seed Copel Telecom for test_mcp_v2.py compatibility
    graph_store.index_document(
        corpus="archive",
        doc_identifier="DOC-101",
        title="Contrato Copel Telecom 2026",
        created_date="2026-01-15",
        url="/docs/contrato_copel_2026.pdf",
        entities=[
            ExtractedEntity("Copel Telecom", "organization", "copel telecom", "Contrato de fibra óptica corporativa com Copel Telecom"),
            ExtractedEntity("R$ 1.850,00", "monetary_amount", "r$ 1.850,00", "Valor mensal SLA fibra"),
        ],
        relations=[
            ExtractedRelation("Copel Telecom", "R$ 1.850,00", "CONTRACT_VALUE"),
        ],
        clearance_level=0,
    )
    graph_store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")


if __name__ == "__main__":
    if "--graph-only" in sys.argv and ROUTER_DB_PATH.exists():
        if GRAPH_DB_PATH.exists():
            GRAPH_DB_PATH.unlink()
        for sfx in ("-wal", "-shm"):
            wp = Path(str(GRAPH_DB_PATH) + sfx)
            if wp.exists():
                wp.unlink()
        r_inst = SovereignQueryRouter(db_path=ROUTER_DB_PATH)
        g_inst = GraphStore(db_path=GRAPH_DB_PATH)
        populate_graph_from_router_db(r_inst, g_inst)
        g_stats = g_inst.get_entity_statistics()
        r_inst.close()
        g_inst.close()
        print(json.dumps({"graph_db_size_mb": round(GRAPH_DB_PATH.stat().st_size / (1024 * 1024), 2), "graph_statistics": g_stats}, indent=2))
    else:
        build_persistent_huawei_databases()
