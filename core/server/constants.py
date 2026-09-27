"""
Constants, path resolution, and common extractors for the Sovereign Server.
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Any

DEFAULT_HOST = os.getenv("SOVEREIGN_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("SOVEREIGN_PORT", "8765"))

_APPLIANCE_ROOT = Path(__file__).resolve().parent.parent.parent
_CANONICAL_PROD_VAULT = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault")
_PROD_VAULT_DIR = (
    _CANONICAL_PROD_VAULT
    if _CANONICAL_PROD_VAULT.exists()
    else (
        (_APPLIANCE_ROOT.parent.parent / "docs" / ".aegis_vault")
        if (_APPLIANCE_ROOT.parent.parent / "docs" / ".aegis_vault").exists()
        else (_APPLIANCE_ROOT / "data")
    )
)
_LEGACY_DATA_DIR = _APPLIANCE_ROOT / "data"
WEB_PORTAL_INDEX = _APPLIANCE_ROOT / "web" / "portal" / "index.html"


def _resolve_default_router_db() -> Path:
    env_p = (
        os.getenv("ROUTER_DB_PATH")
        or os.getenv("SOVEREIGN_ROUTER_DB")
        or os.getenv("SOVEREIGN_ROUTER_DB_PATH")
    )
    if env_p and Path(env_p).exists() and Path(env_p).stat().st_size > 0:
        return Path(env_p)
    if (_PROD_VAULT_DIR / "sovereign_router.db").exists() and (_PROD_VAULT_DIR / "sovereign_router.db").stat().st_size > 0:
        return _PROD_VAULT_DIR / "sovereign_router.db"
    if (_CANONICAL_PROD_VAULT / "sovereign_router.db").exists() and (_CANONICAL_PROD_VAULT / "sovereign_router.db").stat().st_size > 0:
        return _CANONICAL_PROD_VAULT / "sovereign_router.db"
    if (_LEGACY_DATA_DIR / "sovereign_router.db").exists():
        return _LEGACY_DATA_DIR / "sovereign_router.db"
    if (_PROD_VAULT_DIR / "sovereign_huawei_router.db").exists():
        return _PROD_VAULT_DIR / "sovereign_huawei_router.db"
    return _LEGACY_DATA_DIR / "sovereign_huawei_router.db"


def _resolve_default_graph_db() -> Path:
    env_p = (
        os.getenv("GRAPH_DB_PATH")
        or os.getenv("SOVEREIGN_GRAPH_DB")
        or os.getenv("SOVEREIGN_GRAPH_DB_PATH")
    )
    if env_p and Path(env_p).exists() and Path(env_p).stat().st_size > 0:
        return Path(env_p)
    if (_PROD_VAULT_DIR / "sovereign_graph.db").exists() and (_PROD_VAULT_DIR / "sovereign_graph.db").stat().st_size > 0:
        return _PROD_VAULT_DIR / "sovereign_graph.db"
    if (_CANONICAL_PROD_VAULT / "sovereign_graph.db").exists() and (_CANONICAL_PROD_VAULT / "sovereign_graph.db").stat().st_size > 0:
        return _CANONICAL_PROD_VAULT / "sovereign_graph.db"
    if (_LEGACY_DATA_DIR / "sovereign_graph.db").exists():
        return _LEGACY_DATA_DIR / "sovereign_graph.db"
    if (_PROD_VAULT_DIR / "sovereign_huawei_graph.db").exists():
        return _PROD_VAULT_DIR / "sovereign_huawei_graph.db"
    return _LEGACY_DATA_DIR / "sovereign_huawei_graph.db"


DEFAULT_ROUTER_DB = _resolve_default_router_db()
DEFAULT_GRAPH_DB = _resolve_default_graph_db()
DEFAULT_HUAWEI_ROUTER_DB = DEFAULT_ROUTER_DB
DEFAULT_HUAWEI_GRAPH_DB = DEFAULT_GRAPH_DB
DEFAULT_DIAGRAMS_DIR = (
    _PROD_VAULT_DIR / "extracted_diagrams"
    if (_PROD_VAULT_DIR / "extracted_diagrams").exists()
    else _LEGACY_DATA_DIR / "extracted_diagrams"
)
MONITORED_SOURCES_FILE = (
    _PROD_VAULT_DIR / "monitored_sources.json"
    if _PROD_VAULT_DIR.exists()
    else _LEGACY_DATA_DIR / "monitored_sources.json"
)
ACTIVE_LICENSE_FILE = (
    _PROD_VAULT_DIR / "active_license.json"
    if _PROD_VAULT_DIR.exists()
    else _LEGACY_DATA_DIR / "active_license.json"
)
LICENSE_KEYS_FILE = (
    _PROD_VAULT_DIR / "license_keys.json"
    if _PROD_VAULT_DIR.exists()
    else _LEGACY_DATA_DIR / "license_keys.json"
)


def _extract_structured_sections(raw_text: str) -> Dict[str, str]:
    """Extracts structured telecom/compliance sections (Description, Possible Causes, Procedure, Impact, Parameters)."""
    if not raw_text:
        return {}
    clean = re.sub(r"^Virtual URI:\s*archive://[^\n]+\n+", "", raw_text, flags=re.M)
    headings = [
        "Description",
        "Attribute",
        "Parameters",
        "Impact on the System",
        "Possible Causes",
        "Procedure",
        "Related Information",
    ]
    body_start = min(380, len(clean) // 5)
    positions = []
    for h in headings:
        idx = clean.find(f"\n{h}\n", body_start)
        if idx == -1:
            idx = clean.find(f"\n{h}", body_start)
        if idx == -1:
            idx = clean.find(f"{h}\n", 0)
        if idx != -1:
            positions.append((idx, h))
    positions.sort(key=lambda x: x[0])
    sections: Dict[str, str] = {}
    for i, (pos, h) in enumerate(positions):
        start_idx = pos + len(h) + 1
        end_idx = positions[i + 1][0] if i + 1 < len(positions) else len(clean)
        sec_body = clean[start_idx:end_idx].strip()
        if sec_body and h not in sections:
            sections[h] = sec_body[:2500]
    if not sections and clean.strip():
        sections["Description"] = clean.strip()[:2000]
    return sections


def _detect_and_parse_markdown_tables(text: str) -> Dict[str, Any]:
    """
    Detects if text contains Markdown or spreadsheet tables (| ... | ... |).
    Supports both standard markdown tables with separator lines (| --- | --- |)
    and OpenXML spreadsheet extracts with consecutive pipe-delimited rows.
    Returns dict with 'has_table': bool and 'table_headers': List[str].
    """
    if not text or "|" not in text:
        return {"has_table": False, "table_headers": []}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    headers: List[str] = []
    has_table = False

    for i in range(len(lines)):
        line = lines[i]
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            # Check 1: Next line is a markdown table separator: | --- | --- | or |:---|:---|
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("|") and next_line.endswith("|") and ("-" in next_line or ":" in next_line):
                    sep_cells = [c.strip() for c in next_line.strip("|").split("|")]
                    non_empty_sep = [c for c in sep_cells if c]
                    if len(non_empty_sep) >= 1 and all(re.match(r"^:?-{1,}:?$", c) for c in non_empty_sep):
                        cols = [c.strip() for c in line.strip("|").split("|")]
                        for col in cols:
                            clean_col = re.sub(r"[*`_]", "", col).strip()
                            if clean_col and clean_col not in headers:
                                headers.append(clean_col)
                        has_table = True
                        break

            # Check 2: Next line is another pipe-delimited row (OpenXML spreadsheet extract)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if next_line.startswith("|") and next_line.endswith("|") and next_line.count("|") >= 2:
                    cols = [c.strip() for c in line.strip("|").split("|")]
                    for col in cols:
                        clean_col = re.sub(r"[*`_]", "", col).strip()
                        if clean_col and clean_col not in headers:
                            headers.append(clean_col)
                    has_table = True
                    break

    return {"has_table": has_table, "table_headers": headers}

