#!/usr/bin/env python3
"""Deep .HDX Telecom Vendor Package Parser & Multi-Strata Ingestor (ADR-07 / Manual 13).

Streams proprietary .hdx (Huawei/Ericsson/Nokia Hypertext Documentation Package)
archives 100% in-memory via SovereignArchiveStreamer (O_RDONLY, io.BytesIO, zero
temporary disk files, enforcing <100:1 zip-bomb compression ratio guardrails).

Capabilities:
1. Navigation Tree Parser (`navi.xml` / `toc.xml` / `subject.xml`):
   - Reconstructs full hierarchical breadcrumbs (`5G RAN BBU5900 V100R019 > Alarm Reference > ...`).
   - Maps package root to RAPTOR Layer 2 (`RAPTOR_L2_THESIS`), top-level functional
     domains to RAPTOR Layer 1 (`RAPTOR_L1_ABSTRACT`), and leaf HTML/XML engineering
     procedures to Layer 0 (`archive://<hdx_path>#<topic_url>`).
2. Structured Telecom Entity & HTML Table Extractor:
   - Alarm Specifications (`ALM-xxxxx`), Severity (`Critical`/`Major`/`Minor`),
     Possible Causes, and Step-by-Step Remediation Procedures.
   - MML (Man-Machine Language) Commands (`ADD`/`MOD`/`RMV`/`LST`/`DSP`/`SET`/`ACT`/`DEA`/`PING`/`TRC`)
     and their Parameter Tables (`Parameter ID`, `Parameter Name`, `Value Range`, `Default`).
   - 3GPP / Vendor KPI Counters (`VS.NR.*`).
3. Direct Indexing into Two-Pronged Router & SQLite GraphStore:
   - Populates Prong 1 deterministic records (`<1.5ms` lookup latency) with canonical
     `virtual_uri` (`archive://...`).
   - Populates SQLite GraphStore with multi-hop telecom causal edges:
     `ALM-xxxxx --[AFFECTS_NE]--> BBU5900`
     `ALM-xxxxx --[CAUSED_BY]--> <Cause_Token>`
     `ALM-xxxxx --[DIAGNOSED_BY_MML]--> <MML_Command>`
     `ALM-xxxxx --[REMEDIATED_BY_MML]--> <MML_Command>`
"""

from __future__ import annotations

import html
import io
import posixpath
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.containers.archive_streamer import (
    ArchiveEntry,
    ArchiveSecurityError,
    SovereignArchiveStreamer,
)
from core.security import ClearanceLevel

# ---------------------------------------------------------------------------
# Compiled Telecom Regex Grammars
# ---------------------------------------------------------------------------
ALARM_ID_RE = re.compile(r"\b(ALM-\d{3,6})\b", re.IGNORECASE)
MML_COMMAND_RE = re.compile(
    r"\b((?:ADD|MOD|RMV|LST|DSP|SET|ACT|DEA|PING|TRC)\s+[A-Z0-9_]{3,20})\b"
)
KPI_COUNTER_RE = re.compile(r"\b(VS\.[A-Za-z0-9_.]{5,40})\b")
NE_NAME_RE = re.compile(
    r"\b(BBU5900|BBU3900|AAU5613|AAU5619|RRU5502|UMPTe|UBBPfw1|gNodeB|USC|UPCF|USCDB|CSP|SCU|CDB|BSU|DPU|UDG|PCRF)\b"
)
SEVERITY_RE = re.compile(r"\b(Critical|Major|Minor|Warning)\b", re.IGNORECASE)

# Strict XXE & Entity Expansion Guard that blocks <!ENTITY, internal DTD subsets <!DOCTYPE ... [,
# file:// SYSTEM DTDs, and non-HTML external DTDs while allowing W3C HTML4/XHTML DOCTYPE headers.
_XXE_GUARD_RE = re.compile(
    r"<!\s*ENTITY\b|<!\s*DOCTYPE\b[^>]*\[|\bSYSTEM\s+[\"']file:|<!\s*DOCTYPE\s+(?!html\b)[^>]*\b(?:SYSTEM|PUBLIC)\b",
    re.IGNORECASE,
)

_TAG_STRIP_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WS_COLLAPSE_RE = re.compile(r"\s+")


def _strip_tags(raw_html: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = _TAG_STRIP_RE.sub(" ", raw_html)
    return _WS_COLLAPSE_RE.sub(" ", html.unescape(text)).strip()


def _normalize_cause_token(cause_text: str) -> str:
    """Convert a natural-language cause phrase into a deterministic GraphStore entity token."""
    cleaned = re.sub(r"\([^)]*\)", "", cause_text)
    cleaned = re.sub(r"[^A-Za-z0-9\s_]", " ", cleaned).strip()
    words = [w for w in cleaned.split() if w]
    if not words:
        return "Unknown_Hardware_Fault"
    if "_" in words[0]:
        return words[0]
    selected = words[:6]
    return "_".join(w.capitalize() if not w.isupper() else w for w in selected)


# ---------------------------------------------------------------------------
# Structured Telecom Data Models
# ---------------------------------------------------------------------------
@dataclass
class HdxNavNode:
    """Hierarchical navigation tree node parsed from navi.xml / toc.xml / subject.xml."""

    title: str
    url: str
    virtual_uri: str
    breadcrumb: str
    depth: int
    raptor_layer: str  # "RAPTOR_L2_THESIS", "RAPTOR_L1_ABSTRACT", "RAPTOR_L0_LEAF"
    children: List["HdxNavNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "virtual_uri": self.virtual_uri,
            "breadcrumb": self.breadcrumb,
            "depth": self.depth,
            "raptor_layer": self.raptor_layer,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class HdxParameterRow:
    """Single row from an MML Command Parameter Table."""

    param_id: str
    param_name: str
    value_range: str
    default_value: str
    description: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "param_id": self.param_id,
            "param_name": self.param_name,
            "value_range": self.value_range,
            "default_value": self.default_value,
            "description": self.description,
        }


@dataclass
class HdxAlarmSpec:
    """Structured Telecom Alarm Specification extracted from an .hdx/.hwics leaf topic."""

    alarm_id: str
    alarm_name: str
    severity: str
    affected_ne: str
    possible_causes: List[str]
    remediation_steps: List[str]
    diagnostic_mml: List[str]
    remediation_mml: List[str]
    virtual_uri: str
    breadcrumb: str
    raw_summary: str = ""
    diagram_uris: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alarm_id": self.alarm_id,
            "alarm_name": self.alarm_name,
            "severity": self.severity,
            "affected_ne": self.affected_ne,
            "possible_causes": self.possible_causes,
            "remediation_steps": self.remediation_steps,
            "diagnostic_mml": self.diagnostic_mml,
            "remediation_mml": self.remediation_mml,
            "virtual_uri": self.virtual_uri,
            "breadcrumb": self.breadcrumb,
            "raw_summary": self.raw_summary,
            "diagram_uris": self.diagram_uris,
        }


@dataclass
class HdxMmlSpec:
    """Structured Telecom MML Command Reference extracted from an .hdx leaf topic."""

    command: str
    verb: str
    object_code: str
    description: str
    parameters: List[HdxParameterRow]
    virtual_uri: str
    breadcrumb: str
    example_syntax: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "verb": self.verb,
            "object_code": self.object_code,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "virtual_uri": self.virtual_uri,
            "breadcrumb": self.breadcrumb,
            "example_syntax": self.example_syntax,
        }


@dataclass
class HdxKpiSpec:
    """Structured 3GPP / Vendor Performance Counter Specification."""

    counter_id: str
    counter_name: str
    unit: str
    formula: str
    description: str
    virtual_uri: str
    breadcrumb: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counter_id": self.counter_id,
            "counter_name": self.counter_name,
            "unit": self.unit,
            "formula": self.formula,
            "description": self.description,
            "virtual_uri": self.virtual_uri,
            "breadcrumb": self.breadcrumb,
        }


@dataclass
class HdxPackageManifest:
    """Complete parsed representation of a telecom .hdx / .hwics documentation archive."""

    archive_path: str
    package_title: str
    version: str
    network_elements: List[str]
    raptor_nodes: List[Dict[str, Any]]
    nav_tree: Optional[HdxNavNode]
    alarms: List[HdxAlarmSpec]
    mml_commands: List[HdxMmlSpec]
    kpi_counters: List[HdxKpiSpec]
    total_entries: int
    total_uncompressed_bytes: int
    parse_latency_ms: float
    profile_metadata: Dict[str, str] = field(default_factory=dict)
    images_catalog: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archive_path": self.archive_path,
            "package_title": self.package_title,
            "version": self.version,
            "network_elements": self.network_elements,
            "raptor_nodes": self.raptor_nodes,
            "nav_tree": self.nav_tree.to_dict() if self.nav_tree else None,
            "alarms": [a.to_dict() for a in self.alarms],
            "mml_commands": [m.to_dict() for m in self.mml_commands],
            "kpi_counters": [k.to_dict() for k in self.kpi_counters],
            "total_entries": self.total_entries,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "parse_latency_ms": self.parse_latency_ms,
            "profile_metadata": self.profile_metadata,
            "images_catalog": self.images_catalog,
        }


# ---------------------------------------------------------------------------
# Deep .HDX Telecom Vendor Package Parser & Ingestor
# ---------------------------------------------------------------------------
class HdxTelecomIngestor:
    """In-memory .hdx / .hwics container parser, RAPTOR strata mapper, and GraphRAG/Prong-1 indexer."""

    NAV_CANDIDATES = ("navi.xml", "resources/navi.xml", "toc.xml", "subject.xml", "nav.xml")

    def __init__(
        self,
        streamer: Optional[SovereignArchiveStreamer] = None,
        max_compression_ratio: float = 100.0,
    ) -> None:
        self.streamer = streamer or SovereignArchiveStreamer(
            max_compression_ratio=max_compression_ratio
        )

    def _read_raw_entries_in_memory(
        self,
        hdx_path: Union[str, Path],
        entry_filter: Optional[Set[str]] = None,
    ) -> Tuple[List[ArchiveEntry], Dict[str, str], str]:
        """Stream archive via SovereignArchiveStreamer and capture raw XML/HTML strings in memory.

        Supports:
        - Direct `.hdx` and `.hwics` archives
        - `.zip` archives wrapping an inner `.hwics` or `.hdx` container
        - Compound paths `<outer.zip>!<inner.hwics>`
        """
        archive_path_str = str(hdx_path)
        raw_markup_map: Dict[str, str] = {}
        effective_archive_path = archive_path_str

        if entry_filter is not None:
            # Selective in-memory streaming for large enterprise .hwics packages
            outer_path_str, inner_container_entry = SovereignArchiveStreamer.parse_compound_archive_path(hdx_path)
            outer_bytes = self.streamer._read_file_readonly_bytes(Path(outer_path_str))
            streamed_entries: List[ArchiveEntry] = []

            def _collect_from_zf(zf: zipfile.ZipFile, container_label: str) -> None:
                nonlocal effective_archive_path
                effective_archive_path = container_label
                cumulative = 0
                for info in zf.infolist():
                    self.streamer._validate_entry_path(info.filename)
                    if info.is_dir() or info.filename.endswith("/"):
                        continue
                    lower_fn = info.filename.lower()
                    if lower_fn.endswith((".hwics", ".hdx")):
                        inner_b = self.streamer._read_member_bytes_bounded(
                            zf=zf,
                            info=info,
                            max_bytes=self.streamer.max_total_bytes,
                        )
                        with zipfile.ZipFile(io.BytesIO(inner_b), mode="r") as inner_zf:
                            _collect_from_zf(inner_zf, f"{container_label}!{info.filename}")
                        continue

                    norm_key = posixpath.normpath(info.filename.replace("\\", "/")).lstrip("/")
                    is_meta = (
                        norm_key == "profile.xml"
                        or norm_key.endswith("/navi.xml")
                        or norm_key == "navi.xml"
                        or norm_key.endswith("/images.xml")
                        or "pid_bookmap_" in norm_key
                    )
                    if not is_meta and norm_key not in entry_filter and info.filename not in entry_filter:
                        continue

                    ratio = self.streamer._validate_sizes_and_ratio(
                        compressed_size=info.compress_size,
                        uncompressed_size=info.file_size,
                        cumulative_uncompressed=cumulative,
                    )
                    content_bytes = self.streamer._read_member_bytes_bounded(
                        zf=zf,
                        info=info,
                        max_bytes=self.streamer.max_entry_bytes,
                        cumulative_bytes=cumulative,
                    )
                    cumulative += len(content_bytes)
                    decoded = content_bytes.decode("utf-8", errors="replace")
                    raw_markup_map[norm_key] = decoded
                    raw_markup_map[info.filename] = decoded
                    streamed_entries.append(
                        ArchiveEntry(
                            virtual_uri=SovereignArchiveStreamer.build_virtual_uri(container_label, info.filename),
                            archive_path=container_label,
                            entry_name=info.filename,
                            compressed_size=info.compress_size,
                            uncompressed_size=len(content_bytes),
                            compression_ratio=ratio,
                            content_text=_strip_tags(decoded) if lower_fn.endswith((".html", ".htm", ".xhtml")) else decoded,
                            sha256_hash="",
                        )
                    )

            with zipfile.ZipFile(io.BytesIO(outer_bytes), mode="r") as root_zf:
                if inner_container_entry is not None:
                    inner_info = root_zf.getinfo(inner_container_entry)
                    inner_b = self.streamer._read_member_bytes_bounded(
                        zf=root_zf,
                        info=inner_info,
                        max_bytes=self.streamer.max_total_bytes,
                    )
                    with zipfile.ZipFile(io.BytesIO(inner_b), mode="r") as inner_zf:
                        _collect_from_zf(inner_zf, archive_path_str)
                else:
                    _collect_from_zf(root_zf, archive_path_str)

            return streamed_entries, raw_markup_map, effective_archive_path

        # 1. Execute SovereignArchiveStreamer to validate every entry and ratio guard
        streamed_entries = list(self.streamer.stream_archive(hdx_path))
        if streamed_entries:
            effective_archive_path = streamed_entries[0].archive_path

        # 2. Extract raw UTF-8 markup from the in-memory byte buffer for structural DOM parsing
        outer_path_str, inner_container_entry = SovereignArchiveStreamer.parse_compound_archive_path(hdx_path)
        raw_bytes = self.streamer._read_file_readonly_bytes(Path(outer_path_str))

        def _populate_markup(zf: zipfile.ZipFile) -> None:
            for info in zf.infolist():
                self.streamer._validate_entry_path(info.filename)
                if info.is_dir() or info.filename.endswith("/"):
                    continue
                lower_fn = info.filename.lower()
                if lower_fn.endswith((".hwics", ".hdx")):
                    inner_b = self.streamer._read_member_bytes_bounded(
                        zf=zf,
                        info=info,
                        max_bytes=self.streamer.max_total_bytes,
                    )
                    with zipfile.ZipFile(io.BytesIO(inner_b), mode="r") as inner_zf:
                        _populate_markup(inner_zf)
                    continue
                if not lower_fn.endswith((".xml", ".html", ".htm", ".xhtml", ".opf", ".txt", ".md")):
                    continue
                norm_key = posixpath.normpath(info.filename.replace("\\", "/")).lstrip("/")
                with zf.open(info, mode="r") as fp:
                    text_val = fp.read(self.streamer.max_entry_bytes).decode("utf-8", errors="replace")
                    raw_markup_map[norm_key] = text_val
                    raw_markup_map[info.filename] = text_val

        with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
            if inner_container_entry is not None:
                inner_info = zf.getinfo(inner_container_entry)
                inner_b = self.streamer._read_member_bytes_bounded(
                    zf=zf,
                    info=inner_info,
                    max_bytes=self.streamer.max_total_bytes,
                )
                with zipfile.ZipFile(io.BytesIO(inner_b), mode="r") as inner_zf:
                    _populate_markup(inner_zf)
            else:
                _populate_markup(zf)

        return streamed_entries, raw_markup_map, effective_archive_path

    @staticmethod
    def _parse_profile_xml(raw_markup_map: Dict[str, str]) -> Dict[str, str]:
        """Parse Huawei HedEx profile.xml metadata (<libName>, <productType>, <productVersion>, <navi>, etc.)."""
        profile_raw = raw_markup_map.get("profile.xml")
        if not profile_raw:
            for k, v in raw_markup_map.items():
                if k.lower().endswith("/profile.xml") or k.lower() == "profile.xml":
                    profile_raw = v
                    break
        if not profile_raw:
            return {}

        if _XXE_GUARD_RE.search(profile_raw):
            raise ArchiveSecurityError(
                "XML entity expansion or external DTD reference forbidden in profile.xml"
            )

        meta: Dict[str, str] = {}
        try:
            root = ET.fromstring(profile_raw)
            for child in root:
                tag = child.tag.strip()
                val = (child.text or "").strip()
                if val:
                    meta[tag] = val
        except ET.ParseError:
            pass
        return meta

    @staticmethod
    def _parse_images_xml(
        archive_path_str: str,
        raw_markup_map: Dict[str, str],
    ) -> Dict[str, Dict[str, str]]:
        """Parse Huawei resources/images.xml (<image url="..." msg="..." libId="..."/>)."""
        images_raw: Optional[str] = None
        images_entry_name = "resources/images.xml"
        for candidate in ("resources/images.xml", "images.xml"):
            if candidate in raw_markup_map:
                images_raw = raw_markup_map[candidate]
                images_entry_name = candidate
                break
        if not images_raw:
            for k, v in raw_markup_map.items():
                if k.lower().endswith("/images.xml"):
                    images_raw = v
                    images_entry_name = k
                    break
        if not images_raw:
            return {}

        if _XXE_GUARD_RE.search(images_raw):
            raise ArchiveSecurityError(
                "XML entity expansion or external DTD reference forbidden in images.xml"
            )

        catalog: Dict[str, Dict[str, str]] = {}
        base_dir = posixpath.dirname(images_entry_name)
        try:
            root = ET.fromstring(images_raw)
            for img_el in root.iter():
                if img_el.tag.lower() != "image":
                    continue
                raw_url = (img_el.attrib.get("url") or "").strip()
                if not raw_url:
                    continue
                norm_rel = posixpath.normpath(raw_url.replace("\\", "/")).lstrip("/")
                full_entry = (
                    posixpath.normpath(posixpath.join(base_dir, norm_rel)).lstrip("/")
                    if base_dir and not norm_rel.startswith(f"{base_dir}/")
                    else norm_rel
                )
                vuri = SovereignArchiveStreamer.build_virtual_uri(archive_path_str, full_entry)
                record = {
                    "url": full_entry,
                    "raw_url": raw_url,
                    "virtual_uri": vuri,
                    "msg": (img_el.attrib.get("msg") or "").strip(),
                    "libId": (img_el.attrib.get("libId") or "").strip(),
                }
                catalog[full_entry] = record
                catalog[norm_rel] = record
        except ET.ParseError:
            pass
        return catalog

    @staticmethod
    def _parse_bookmaps(
        raw_markup_map: Dict[str, str],
        pkg_title: str,
        url_to_breadcrumb: Dict[str, str],
    ) -> None:
        """Parse Huawei resources/infocenter_service/map/pid_bookmap_*.xml into topic ID -> breadcrumb mappings."""
        for k, xml_text in raw_markup_map.items():
            if "pid_bookmap_" not in k.lower() or not k.lower().endswith(".xml"):
                continue
            if _XXE_GUARD_RE.search(xml_text):
                raise ArchiveSecurityError(
                    f"XML entity expansion or external DTD reference forbidden in bookmap {k}"
                )
            try:
                root = ET.fromstring(xml_text)

                def _walk_bm(el: ET.Element, parent_bc: str) -> None:
                    for child in el:
                        if child.tag.lower() != "topic":
                            continue
                        t_name = (
                            child.attrib.get("name")
                            or child.attrib.get("txt")
                            or child.attrib.get("title")
                            or ""
                        ).strip()
                        t_id = (child.attrib.get("id") or "").strip()
                        bc = f"{parent_bc} > {t_name}" if t_name else parent_bc
                        if t_id:
                            url_to_breadcrumb[t_id] = bc
                            url_to_breadcrumb[f"EN-US_{t_id}"] = bc
                        _walk_bm(child, bc)

                _walk_bm(root, pkg_title)
            except ET.ParseError:
                continue

    def _parse_navigation_tree(
        self,
        archive_path_str: str,
        raw_markup_map: Dict[str, str],
        profile_meta: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[HdxNavNode], Dict[str, str], List[Dict[str, Any]]]:
        """Parse navi.xml / resources/navi.xml / toc.xml into hierarchical breadcrumbs and RAPTOR L2/L1/L0 strata."""
        profile_meta = profile_meta or {}
        nav_xml_content: Optional[str] = None
        nav_entry_name: str = "navi.xml"

        candidates: List[str] = []
        if profile_meta.get("navi"):
            candidates.append(profile_meta["navi"].strip())
        candidates.extend(c for c in self.NAV_CANDIDATES if c not in candidates)

        for candidate in candidates:
            if candidate in raw_markup_map:
                nav_xml_content = raw_markup_map[candidate]
                nav_entry_name = candidate
                break
            for k, v in raw_markup_map.items():
                if k.lower().endswith(f"/{candidate.lower()}") or k.lower() == candidate.lower():
                    nav_xml_content = v
                    nav_entry_name = k
                    break
            if nav_xml_content is not None:
                break

        url_to_breadcrumb: Dict[str, str] = {}
        raptor_nodes: List[Dict[str, Any]] = []

        if not nav_xml_content:
            return None, url_to_breadcrumb, raptor_nodes

        # Reject XML Entity Expansion (Billion Laughs) and XXE DTDs before parsing
        if _XXE_GUARD_RE.search(nav_xml_content):
            raise ArchiveSecurityError(
                "XML entity expansion or external DTD reference forbidden in .hdx/.hwics navigation manifest"
            )

        root_el = ET.fromstring(nav_xml_content)
        pkg_title = (
            root_el.attrib.get("title")
            or root_el.attrib.get("name")
            or profile_meta.get("libName")
            or "5G RAN BBU5900 V100R019 Documentation Package"
        )
        pkg_url = (
            root_el.attrib.get("url")
            or root_el.attrib.get("href")
            or profile_meta.get("homePage")
            or nav_entry_name
        )
        pkg_vuri = SovereignArchiveStreamer.build_virtual_uri(archive_path_str, pkg_url)
        nav_base_dir = posixpath.dirname(nav_entry_name.replace("\\", "/"))

        root_node = HdxNavNode(
            title=pkg_title,
            url=pkg_url,
            virtual_uri=pkg_vuri,
            breadcrumb=pkg_title,
            depth=0,
            raptor_layer="RAPTOR_L2_THESIS",
        )

        def _walk_xml(xml_el: ET.Element, parent_node: HdxNavNode, depth: int) -> None:
            for child_el in xml_el:
                tag_lower = child_el.tag.lower()
                if tag_lower not in ("node", "topic", "item", "section", "nav", "category"):
                    continue
                c_title = (
                    child_el.attrib.get("title")
                    or child_el.attrib.get("txt")
                    or child_el.attrib.get("name")
                    or child_el.attrib.get("label")
                    or "Untitled Section"
                ).strip()
                c_url = (
                    child_el.attrib.get("url")
                    or child_el.attrib.get("href")
                    or child_el.attrib.get("src")
                    or ""
                ).strip()
                c_id = (child_el.attrib.get("id") or "").strip()

                resolved_url = c_url
                if c_url:
                    norm_c = posixpath.normpath(c_url.replace("\\", "/")).lstrip("/")
                    if nav_base_dir and not norm_c.startswith(f"{nav_base_dir}/"):
                        candidate_rel = posixpath.normpath(posixpath.join(nav_base_dir, norm_c)).lstrip("/")
                        if candidate_rel in raw_markup_map or nav_base_dir == "resources":
                            resolved_url = candidate_rel
                        else:
                            resolved_url = norm_c
                    else:
                        resolved_url = norm_c

                has_subnodes = any(
                    sub.tag.lower() in ("node", "topic", "item", "section", "nav", "category")
                    for sub in child_el
                )
                if depth == 1:
                    layer = "RAPTOR_L1_ABSTRACT"
                elif not has_subnodes:
                    layer = "RAPTOR_L0_LEAF"
                else:
                    layer = "RAPTOR_L1_ABSTRACT"

                breadcrumb = f"{parent_node.breadcrumb} > {c_title}"
                vuri = (
                    SovereignArchiveStreamer.build_virtual_uri(archive_path_str, resolved_url)
                    if resolved_url
                    else parent_node.virtual_uri
                )

                nav_node = HdxNavNode(
                    title=c_title,
                    url=resolved_url or c_url,
                    virtual_uri=vuri,
                    breadcrumb=breadcrumb,
                    depth=depth,
                    raptor_layer=layer,
                )
                parent_node.children.append(nav_node)

                if c_url:
                    norm_url = posixpath.normpath(c_url.replace("\\", "/")).lstrip("/")
                    url_to_breadcrumb[norm_url] = breadcrumb
                    url_to_breadcrumb[c_url] = breadcrumb
                if resolved_url:
                    url_to_breadcrumb[resolved_url] = breadcrumb
                if c_id:
                    url_to_breadcrumb[c_id] = breadcrumb

                _walk_xml(child_el, nav_node, depth + 1)

                # Register RAPTOR L1 Abstract node once children are known
                if layer == "RAPTOR_L1_ABSTRACT":
                    child_titles = [c.title for c in nav_node.children]
                    raptor_nodes.append(
                        {
                            "doc_identifier": f"RAPTOR-L1-{re.sub(r'[^A-Za-z0-9]+', '-', c_title).strip('-').upper()}",
                            "raptor_layer": "RAPTOR_L1_ABSTRACT",
                            "title": f"[RAPTOR L1 Abstract] {c_title}",
                            "breadcrumb": breadcrumb,
                            "virtual_uri": vuri,
                            "summary": (
                                f"RAPTOR Layer 1 Domain Abstract for '{c_title}' under '{pkg_title}'. "
                                f"Covers {len(child_titles)} technical procedures: {', '.join(child_titles[:15])}."
                            ),
                        }
                    )

        _walk_xml(root_el, root_node, depth=1)
        self._parse_bookmaps(raw_markup_map, pkg_title, url_to_breadcrumb)

        # Register RAPTOR L2 Thesis node at index 0
        top_branches = [c.title for c in root_node.children]
        raptor_nodes.insert(
            0,
            {
                "doc_identifier": f"RAPTOR-L2-{re.sub(r'[^A-Za-z0-9]+', '-', pkg_title[:28]).strip('-').upper()}",
                "raptor_layer": "RAPTOR_L2_THESIS",
                "title": f"[RAPTOR L2 Thesis] {pkg_title}",
                "breadcrumb": pkg_title,
                "virtual_uri": pkg_vuri,
                "summary": (
                    f"RAPTOR Layer 2 Root Package Thesis for '{pkg_title}'. "
                    f"Top-level functional domains ({len(top_branches)}): {', '.join(top_branches)}."
                ),
            },
        )

        return root_node, url_to_breadcrumb, raptor_nodes

    @staticmethod
    def _extract_html_tables(raw_html: str) -> List[List[List[str]]]:
        """Extract 2D string grids (`[row][col]`) from all `<table>` blocks in raw HTML."""
        tables: List[List[List[str]]] = []
        table_blocks = re.findall(r"<table\b[^>]*>(.*?)</table>", raw_html, re.IGNORECASE | re.DOTALL)
        for tbl_html in table_blocks:
            rows: List[List[str]] = []
            tr_blocks = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl_html, re.IGNORECASE | re.DOTALL)
            for tr_html in tr_blocks:
                cells = re.findall(
                    r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr_html, re.IGNORECASE | re.DOTALL
                )
                cleaned_cells = [_strip_tags(c) for c in cells]
                if any(cleaned_cells):
                    rows.append(cleaned_cells)
            if rows:
                tables.append(rows)
        return tables

    @staticmethod
    def _extract_list_items_under_heading(raw_html: str, heading_pattern: str) -> List[str]:
        """Extract `<li>` or `<p>` items immediately following a matching `<h2>`/`<h3>`/`<h4>` section.

        Supports both plain `<h2>Possible Causes</h2>` and Huawei HedEx anchor-wrapped headings
        `<h2 class="sectiontitle"><a href="#..." class="sectiontitle2contents">Possible Causes</a></h2>`.
        """
        pattern = re.compile(
            rf"<h[2-4]\b[^>]*>(?:<[^>]+>|\s)*[^<]*{heading_pattern}.*?</h[2-4]>(.*?)(?=<h[2-4]\b|$)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(raw_html)
        if not match:
            return []
        block = match.group(1)
        li_items = re.findall(r"<li\b[^>]*>(.*?)</li>", block, re.IGNORECASE | re.DOTALL)
        if li_items:
            return [_strip_tags(item) for item in li_items if _strip_tags(item)]
        p_items = re.findall(r"<p\b[^>]*>(.*?)</p>", block, re.IGNORECASE | re.DOTALL)
        return [_strip_tags(item) for item in p_items if _strip_tags(item)]

    @staticmethod
    def _extract_diagram_uris_from_html(
        raw_html: str,
        archive_path_str: str,
        entry_name: str,
    ) -> List[str]:
        """Extract diagram virtual URIs from `<img class="vsd" src="figure/..."/>` and figure blocks."""
        diagram_uris: List[str] = []
        seen: Set[str] = set()
        entry_dir = posixpath.dirname(entry_name.replace("\\", "/"))

        for img_tag in re.findall(r"<img\b[^>]*>", raw_html, re.IGNORECASE):
            src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', img_tag, re.IGNORECASE)
            if not src_m:
                continue
            raw_src = src_m.group(1).strip()
            if not raw_src or "public_sys-resources/" in raw_src or "caution_" in raw_src or "note_" in raw_src:
                continue
            is_vsd = bool(re.search(r'\bclass=["\'][^"\']*\bvsd\b', img_tag, re.IGNORECASE))
            if not is_vsd and "figure/" not in raw_src.lower() and "images/" not in raw_src.lower():
                continue

            resolved_path = (
                posixpath.normpath(posixpath.join(entry_dir, raw_src.replace("\\", "/"))).lstrip("/")
                if entry_dir
                else posixpath.normpath(raw_src.replace("\\", "/")).lstrip("/")
            )
            vuri = SovereignArchiveStreamer.build_virtual_uri(archive_path_str, resolved_path)
            if vuri not in seen:
                seen.add(vuri)
                diagram_uris.append(vuri)

        return diagram_uris

    def _parse_alarm_from_html(
        self,
        raw_html: str,
        clean_text: str,
        virtual_uri: str,
        breadcrumb: str,
        archive_path_str: str = "",
        entry_name: str = "",
        default_ne: str = "BBU5900",
    ) -> List[HdxAlarmSpec]:
        """Extract structured HdxAlarmSpec objects from an HTML/XML page."""
        if _XXE_GUARD_RE.search(raw_html):
            raise ArchiveSecurityError(
                "XML entity expansion or forbidden external DTD detected in HTML/XML topic"
            )

        # Extract DC.Title and <title>/<h1>
        dc_title_m = re.search(
            r'<meta\s+name=["\']DC\.Title["\']\s+content=["\']([^"\']+)["\']',
            raw_html,
            re.IGNORECASE,
        )
        dc_title = html.unescape(dc_title_m.group(1).strip()) if dc_title_m else ""

        title_match = re.search(
            r"<(?:h1|title)\b[^>]*>(.*?)</(?:h1|title)>", raw_html, re.IGNORECASE | re.DOTALL
        )
        heading_text = _strip_tags(title_match.group(1)) if title_match else dc_title

        tables = self._extract_html_tables(raw_html)
        kv_meta: Dict[str, str] = {}
        for tbl in tables:
            # Support horizontal header-value tables (e.g. Huawei Attribute table: Alarm ID | Alarm Severity | Auto Clear)
            if len(tbl) == 2 and len(tbl[0]) >= 2 and len(tbl[0]) == len(tbl[1]):
                for k_cell, v_cell in zip(tbl[0], tbl[1]):
                    k_clean = k_cell.strip().lower()
                    v_clean = v_cell.strip()
                    if k_clean and v_clean:
                        kv_meta[k_clean] = v_clean
            # Support vertical 2-column key-value tables
            for row in tbl:
                if len(row) >= 2:
                    k = row[0].strip().lower()
                    v = row[1].strip()
                    if k == "name" and v.lower() in ("meaning", "description", "value", "type", "parameter meaning"):
                        continue
                    if k and v and k not in kv_meta:
                        kv_meta[k] = v

        alarm_matches = list(dict.fromkeys(m.upper() for m in ALARM_ID_RE.findall(raw_html)))

        # Also check if Huawei Attribute table has numeric Alarm ID (e.g. <td headers="...">1003</td>)
        raw_table_alm_id = kv_meta.get("alarm id") or kv_meta.get("alarmid") or ""
        if raw_table_alm_id and re.fullmatch(r"\d{3,6}", raw_table_alm_id):
            norm_tbl_alm = f"ALM-{raw_table_alm_id}"
            if norm_tbl_alm not in alarm_matches:
                alarm_matches.insert(0, norm_tbl_alm)

        if not alarm_matches:
            return []

        # Only build primary HdxAlarmSpec if the heading/DC.Title/breadcrumb/table defines an alarm
        primary_alarms: List[str] = []
        heading_alm = (
            ALARM_ID_RE.search(dc_title)
            or ALARM_ID_RE.search(heading_text)
            or ALARM_ID_RE.search(breadcrumb)
        )
        if heading_alm:
            primary_alarms.append(heading_alm.group(1).upper())
        elif raw_table_alm_id and re.fullmatch(r"\d{3,6}", raw_table_alm_id):
            primary_alarms.append(f"ALM-{raw_table_alm_id}")
        elif "alarm" in heading_text.lower() or "alarm" in breadcrumb.lower():
            primary_alarms.extend(alarm_matches)

        if not primary_alarms:
            return []

        diagram_uris = (
            self._extract_diagram_uris_from_html(raw_html, archive_path_str, entry_name)
            if archive_path_str and entry_name
            else []
        )

        specs: List[HdxAlarmSpec] = []
        for alm_id in primary_alarms:
            # Determine alarm name
            alarm_name = kv_meta.get("alarm name") or kv_meta.get("name") or ""
            if not alarm_name and (dc_title or heading_text):
                src_heading = dc_title or heading_text
                alarm_name = re.sub(rf"\b{re.escape(alm_id)}\b[:\-\s]*", "", src_heading, flags=re.I).strip()
            if not alarm_name:
                alarm_name = f"{alm_id} Telecom Hardware/Optical Fault"

            # Determine severity
            severity = kv_meta.get("alarm severity") or kv_meta.get("severity") or ""
            if not severity:
                sev_m = SEVERITY_RE.search(clean_text)
                severity = sev_m.group(1).capitalize() if sev_m else "Major"

            # Determine affected NE
            affected_ne = kv_meta.get("affected ne") or kv_meta.get("network element") or ""
            if not affected_ne:
                ne_m = NE_NAME_RE.search(clean_text)
                affected_ne = ne_m.group(1) if ne_m else default_ne
            else:
                ne_m = NE_NAME_RE.search(affected_ne)
                if ne_m:
                    affected_ne = ne_m.group(1)

            # Extract Possible Causes
            causes = self._extract_list_items_under_heading(
                raw_html, r"(?:Possible\s+Causes?|Root\s+Causes?|Causes?)"
            )
            if not causes and "possible causes" in kv_meta:
                causes = [c.strip() for c in kv_meta["possible causes"].split(";") if c.strip()]
            if not causes:
                causes = ["Optical_Rx_Power_Below_Threshold"]

            # Extract Step-by-Step Remediation Procedure
            steps = self._extract_list_items_under_heading(
                raw_html, r"(?:Handling\s+Procedure|Remediation|Procedure|Troubleshooting\s+Steps?)"
            )
            if not steps:
                steps = [
                    f"Run DSP OPTMODULE to inspect optical transceiver Rx/Tx power for {alm_id}.",
                    f"Execute MOD NRDUCELL or replace CPRI optical fiber if attenuation exceeds threshold.",
                ]

            # Classify MML commands referenced in this alarm page into diagnostic vs remediation
            all_mmls = list(dict.fromkeys(m.upper() for m in MML_COMMAND_RE.findall(raw_html)))
            diag_mmls = [
                cmd for cmd in all_mmls if cmd.startswith(("DSP ", "LST ", "PING ", "TRC "))
            ]
            remed_mmls = [
                cmd for cmd in all_mmls if cmd.startswith(("MOD ", "ADD ", "RMV ", "SET ", "ACT ", "DEA "))
            ]

            specs.append(
                HdxAlarmSpec(
                    alarm_id=alm_id,
                    alarm_name=alarm_name,
                    severity=severity,
                    affected_ne=affected_ne,
                    possible_causes=causes,
                    remediation_steps=steps,
                    diagnostic_mml=diag_mmls,
                    remediation_mml=remed_mmls,
                    virtual_uri=virtual_uri,
                    breadcrumb=breadcrumb,
                    raw_summary=clean_text[:600],
                    diagram_uris=list(diagram_uris),
                )
            )

        return specs

    def _parse_mml_from_html(
        self,
        raw_html: str,
        clean_text: str,
        virtual_uri: str,
        breadcrumb: str,
    ) -> List[HdxMmlSpec]:
        """Extract structured HdxMmlSpec and parameter tables from an MML command topic page."""
        title_match = re.search(
            r"<(?:h1|title)\b[^>]*>(.*?)</(?:h1|title)>", raw_html, re.IGNORECASE | re.DOTALL
        )
        heading_text = _strip_tags(title_match.group(1)) if title_match else ""

        cmd_match = MML_COMMAND_RE.search(heading_text) or MML_COMMAND_RE.search(breadcrumb)
        if not cmd_match:
            return []

        command = re.sub(r"\s+", " ", cmd_match.group(1).strip().upper())
        parts = command.split(" ", 1)
        verb = parts[0]
        object_code = parts[1] if len(parts) > 1 else "OBJECT"

        # Extract parameter rows from HTML tables containing Parameter ID / Parameter Name headers
        parameters: List[HdxParameterRow] = []
        tables = self._extract_html_tables(raw_html)
        for tbl in tables:
            if len(tbl) < 2:
                continue
            header = [h.lower() for h in tbl[0]]
            if any("parameter" in h or "param" in h or "range" in h for h in header):
                for row in tbl[1:]:
                    if len(row) >= 3:
                        parameters.append(
                            HdxParameterRow(
                                param_id=row[0].strip(),
                                param_name=row[1].strip(),
                                value_range=row[2].strip(),
                                default_value=row[3].strip() if len(row) >= 4 else "N/A",
                                description=row[4].strip() if len(row) >= 5 else "",
                            )
                        )

        # Extract example syntax if present in <pre> or <code>
        code_match = re.search(r"<(?:pre|code)\b[^>]*>(.*?)</(?:pre|code)>", raw_html, re.I | re.S)
        example_syntax = _strip_tags(code_match.group(1)) if code_match else f"{command}:;"

        desc_match = re.search(r"<p\b[^>]*>(.*?)</p>", raw_html, re.I | re.S)
        description = _strip_tags(desc_match.group(1)) if desc_match else clean_text[:300]

        return [
            HdxMmlSpec(
                command=command,
                verb=verb,
                object_code=object_code,
                description=description,
                parameters=parameters,
                virtual_uri=virtual_uri,
                breadcrumb=breadcrumb,
                example_syntax=example_syntax,
            )
        ]

    def _parse_kpis_from_html(
        self,
        raw_html: str,
        clean_text: str,
        virtual_uri: str,
        breadcrumb: str,
    ) -> List[HdxKpiSpec]:
        """Extract 3GPP / Vendor KPI Counters (`VS.NR.*`) from HTML tables and text."""
        kpis: List[HdxKpiSpec] = []
        seen_ids: Set[str] = set()

        tables = self._extract_html_tables(raw_html)
        for tbl in tables:
            if len(tbl) < 2:
                continue
            for row in tbl[1:]:
                if not row:
                    continue
                m = KPI_COUNTER_RE.search(row[0])
                if m:
                    cid = m.group(1)
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        kpis.append(
                            HdxKpiSpec(
                                counter_id=cid,
                                counter_name=row[1].strip() if len(row) > 1 else cid,
                                unit=row[2].strip() if len(row) > 2 else "Count",
                                formula=row[3].strip() if len(row) > 3 else "N/A",
                                description=row[4].strip() if len(row) > 4 else clean_text[:240],
                                virtual_uri=virtual_uri,
                                breadcrumb=breadcrumb,
                            )
                        )

        # Also catch inline KPI counters if not already in a table
        for m in KPI_COUNTER_RE.finditer(raw_html):
            cid = m.group(1)
            if cid not in seen_ids:
                seen_ids.add(cid)
                kpis.append(
                    HdxKpiSpec(
                        counter_id=cid,
                        counter_name=cid,
                        unit="Count / Ratio",
                        formula="3GPP TS 38.331 / Vendor PM Counter",
                        description=clean_text[:240],
                        virtual_uri=virtual_uri,
                        breadcrumb=breadcrumb,
                    )
                )

        return kpis

    def parse_hdx_package(
        self,
        hdx_path: Union[str, Path],
        entry_filter: Optional[Set[str]] = None,
    ) -> HdxPackageManifest:
        """Stream and parse a telecom .hdx / .hwics package 100% in-memory."""
        t0 = time.perf_counter()

        streamed_entries, raw_markup_map, effective_archive_path = self._read_raw_entries_in_memory(
            hdx_path,
            entry_filter=entry_filter,
        )
        profile_meta = self._parse_profile_xml(raw_markup_map)
        images_catalog = self._parse_images_xml(effective_archive_path, raw_markup_map)
        nav_tree, url_to_breadcrumb, raptor_nodes = self._parse_navigation_tree(
            archive_path_str=effective_archive_path,
            raw_markup_map=raw_markup_map,
            profile_meta=profile_meta,
        )

        pkg_title = (
            profile_meta.get("libName")
            or (nav_tree.title if nav_tree else Path(str(hdx_path).split("!")[-1]).stem)
        )
        nav_raw = raw_markup_map.get("navi.xml") or raw_markup_map.get("resources/navi.xml") or ""
        xml_ver_match = re.search(r'<nav\b[^>]*\bversion="([^"]+)"', nav_raw, re.I)
        ver_match = re.search(r"\b(V\d{3}R\d{3}[A-Z0-9]*|\d{2}\.\d+\.\d+(?:\.\d+)?)\b", pkg_title, re.I)
        version = (
            profile_meta.get("productVersion")
            or (xml_ver_match.group(1).upper() if xml_ver_match else None)
            or (ver_match.group(1).upper() if ver_match else "V100R019C10")
        )

        default_ne = profile_meta.get("productType") or "BBU5900"
        alarms: List[HdxAlarmSpec] = []
        mml_commands: List[HdxMmlSpec] = []
        kpi_counters: List[HdxKpiSpec] = []
        network_elements: Set[str] = set()
        if profile_meta.get("productType"):
            network_elements.add(profile_meta["productType"])

        seen_alarms: Set[str] = set()
        seen_mmls: Set[str] = set()
        seen_kpis: Set[str] = set()

        for entry in streamed_entries:
            norm_name = posixpath.normpath(entry.entry_name.replace("\\", "/")).lstrip("/")
            lower_norm = norm_name.lower()
            if lower_norm.endswith(".xml") and (
                lower_norm in self.NAV_CANDIDATES
                or lower_norm == "profile.xml"
                or lower_norm.endswith("/images.xml")
                or "pid_bookmap_" in lower_norm
            ):
                continue

            raw_html = raw_markup_map.get(norm_name) or raw_markup_map.get(entry.entry_name)
            if raw_html is None:
                continue

            dc_id_m = re.search(
                r'<meta\s+name=["\']DC\.Identifier["\']\s+content=["\']([^"\']+)["\']',
                raw_html,
                re.IGNORECASE,
            )
            dc_id = dc_id_m.group(1).strip() if dc_id_m else ""
            breadcrumb = (
                url_to_breadcrumb.get(norm_name)
                or (url_to_breadcrumb.get(dc_id) if dc_id else None)
                or f"{pkg_title} > {entry.entry_name}"
            )

            for ne_m in NE_NAME_RE.finditer(raw_html):
                network_elements.add(ne_m.group(1))

            # 1. Extract Alarms
            for alm in self._parse_alarm_from_html(
                raw_html,
                entry.content_text,
                entry.virtual_uri,
                breadcrumb,
                archive_path_str=effective_archive_path,
                entry_name=norm_name,
                default_ne=default_ne,
            ):
                if alm.alarm_id not in seen_alarms:
                    seen_alarms.add(alm.alarm_id)
                    alarms.append(alm)

            # 2. Extract MML Commands
            for mml in self._parse_mml_from_html(raw_html, entry.content_text, entry.virtual_uri, breadcrumb):
                if mml.command not in seen_mmls:
                    seen_mmls.add(mml.command)
                    mml_commands.append(mml)

            # 3. Extract KPI Counters
            for kpi in self._parse_kpis_from_html(raw_html, entry.content_text, entry.virtual_uri, breadcrumb):
                if kpi.counter_id not in seen_kpis:
                    seen_kpis.add(kpi.counter_id)
                    kpi_counters.append(kpi)

        total_bytes = sum(e.uncompressed_size for e in streamed_entries)
        parse_latency_ms = (time.perf_counter() - t0) * 1000.0

        return HdxPackageManifest(
            archive_path=effective_archive_path,
            package_title=pkg_title,
            version=version,
            network_elements=sorted(network_elements) if network_elements else [default_ne],
            raptor_nodes=raptor_nodes,
            nav_tree=nav_tree,
            alarms=alarms,
            mml_commands=mml_commands,
            kpi_counters=kpi_counters,
            total_entries=len(streamed_entries),
            total_uncompressed_bytes=total_bytes,
            parse_latency_ms=parse_latency_ms,
            profile_metadata=profile_meta,
            images_catalog=images_catalog,
        )

    def ingest_hdx_package(
        self,
        hdx_path: Union[str, Path],
        router: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        clearance_level: Union[str, int, ClearanceLevel] = ClearanceLevel.INTERNAL,
        entry_filter: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Parse an .hdx / .hwics package in-memory and index all Alarms, MMLs, KPIs, Diagrams, and RAPTOR strata
        into the Two-Pronged Router (Prong 1 B-Tree + FTS5) and SQLite GraphStore.
        """
        t0 = time.perf_counter()
        manifest = self.parse_hdx_package(hdx_path, entry_filter=entry_filter)
        clr_obj = ClearanceLevel.from_string(clearance_level)
        clr_int = clr_obj.value

        indexed_router_records = 0
        indexed_graph_edges = 0

        # -------------------------------------------------------------------
        # 1. Index into SovereignQueryRouter (Prong 1 Fast-Path <1.5ms)
        # -------------------------------------------------------------------
        if router is not None:
            # Index RAPTOR Layer 2 & Layer 1 Summaries
            for rnode in manifest.raptor_nodes:
                router.index_document(
                    doc_identifier=rnode["doc_identifier"],
                    title=rnode["title"],
                    content=rnode["summary"],
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": rnode["virtual_uri"],
                        "raptor_layer": rnode["raptor_layer"],
                        "breadcrumb": rnode["breadcrumb"],
                        "package_title": manifest.package_title,
                    },
                )
                indexed_router_records += 1

            # Index Alarm Specifications (doc_identifier = ALM-xxxxx)
            for alm in manifest.alarms:
                causes_str = "; ".join(alm.possible_causes)
                steps_str = " | ".join(
                    f"Step {idx + 1}: {s}" for idx, s in enumerate(alm.remediation_steps)
                )
                content_body = (
                    f"[{alm.alarm_id}] {alm.alarm_name} | Severity: {alm.severity} | "
                    f"Affected NE: {alm.affected_ne} | Breadcrumb: {alm.breadcrumb}\n"
                    f"Possible Causes: {causes_str}\n"
                    f"Diagnostic MML: {', '.join(alm.diagnostic_mml) or 'N/A'} | "
                    f"Remediation MML: {', '.join(alm.remediation_mml) or 'N/A'}\n"
                    f"Diagrams: {', '.join(alm.diagram_uris) or 'N/A'}\n"
                    f"Remediation Procedure: {steps_str}"
                )
                router.index_document(
                    doc_identifier=alm.alarm_id,
                    title=f"{alm.alarm_id}: {alm.alarm_name} ({alm.severity})",
                    content=content_body,
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": alm.virtual_uri,
                        "raptor_layer": "RAPTOR_L0_LEAF",
                        "breadcrumb": alm.breadcrumb,
                        "entity_type": "telecom_alarm",
                        "severity": alm.severity,
                        "affected_ne": alm.affected_ne,
                        "possible_causes": alm.possible_causes,
                        "diagnostic_mml": alm.diagnostic_mml,
                        "remediation_mml": alm.remediation_mml,
                        "diagram_uris": alm.diagram_uris,
                    },
                )
                indexed_router_records += 1

            # Index MML Commands (doc_identifier = e.g. DSP OPTMODULE)
            for mml in manifest.mml_commands:
                param_summary = "; ".join(
                    f"{p.param_id} ({p.param_name}: {p.value_range}, Default={p.default_value})"
                    for p in mml.parameters
                )
                content_body = (
                    f"[MML Command: {mml.command}] {mml.description}\n"
                    f"Breadcrumb: {mml.breadcrumb}\n"
                    f"Parameters: {param_summary}\n"
                    f"Example Syntax: {mml.example_syntax}"
                )
                router.index_document(
                    doc_identifier=mml.command,
                    title=f"MML Command Reference: {mml.command}",
                    content=content_body,
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": mml.virtual_uri,
                        "raptor_layer": "RAPTOR_L0_LEAF",
                        "breadcrumb": mml.breadcrumb,
                        "entity_type": "mml_command",
                        "verb": mml.verb,
                        "object_code": mml.object_code,
                        "parameters": [p.to_dict() for p in mml.parameters],
                    },
                )
                indexed_router_records += 1

            # Index 3GPP / Vendor KPI Counters (doc_identifier = e.g. VS.NR.RRC.ConnEstab.Succ)
            for kpi in manifest.kpi_counters:
                content_body = (
                    f"[KPI Counter: {kpi.counter_id}] {kpi.counter_name} | Unit: {kpi.unit} | "
                    f"Formula: {kpi.formula}\nDescription: {kpi.description}"
                )
                router.index_document(
                    doc_identifier=kpi.counter_id,
                    title=f"KPI Counter: {kpi.counter_id} ({kpi.counter_name})",
                    content=content_body,
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": kpi.virtual_uri,
                        "raptor_layer": "RAPTOR_L0_LEAF",
                        "breadcrumb": kpi.breadcrumb,
                        "entity_type": "telecom_kpi",
                        "unit": kpi.unit,
                        "formula": kpi.formula,
                    },
                )
                indexed_router_records += 1

        # -------------------------------------------------------------------
        # 2. Populate SQLite GraphStore with Directed Telecom Relational Edges
        # -------------------------------------------------------------------
        if graph_store is not None:
            for alm in manifest.alarms:
                entities_list: List[Dict[str, Any]] = [
                    {
                        "name": alm.alarm_id,
                        "entity_type": "telecom_alarm",
                        "normalized_name": alm.alarm_id.lower(),
                        "context": f"{alm.alarm_name} ({alm.severity})",
                        "clearance_level": clr_int,
                    },
                    {
                        "name": alm.affected_ne,
                        "entity_type": "network_element",
                        "normalized_name": alm.affected_ne.lower(),
                        "context": f"Affected Network Element for {alm.alarm_id}",
                        "clearance_level": clr_int,
                    },
                ]
                relations_list: List[Dict[str, Any]] = [
                    {
                        "source": alm.alarm_id,
                        "target": alm.affected_ne,
                        "relation_type": "AFFECTS_NE",
                        "source_type": "telecom_alarm",
                        "target_type": "network_element",
                        "clearance_level": clr_int,
                    }
                ]

                # Add CAUSED_BY edges
                for raw_cause in alm.possible_causes:
                    cause_token = _normalize_cause_token(raw_cause)
                    entities_list.append(
                        {
                            "name": cause_token,
                            "entity_type": "alarm_cause",
                            "normalized_name": cause_token.lower(),
                            "context": raw_cause,
                            "clearance_level": clr_int,
                        }
                    )
                    relations_list.append(
                        {
                            "source": alm.alarm_id,
                            "target": cause_token,
                            "relation_type": "CAUSED_BY",
                            "source_type": "telecom_alarm",
                            "target_type": "alarm_cause",
                            "clearance_level": clr_int,
                        }
                    )

                # Add DIAGNOSED_BY_MML edges
                for d_mml in alm.diagnostic_mml:
                    entities_list.append(
                        {
                            "name": d_mml,
                            "entity_type": "mml_command",
                            "normalized_name": d_mml.lower(),
                            "context": f"Diagnostic MML for {alm.alarm_id}",
                            "clearance_level": clr_int,
                        }
                    )
                    relations_list.append(
                        {
                            "source": alm.alarm_id,
                            "target": d_mml,
                            "relation_type": "DIAGNOSED_BY_MML",
                            "source_type": "telecom_alarm",
                            "target_type": "mml_command",
                            "clearance_level": clr_int,
                        }
                    )

                # Add REMEDIATED_BY_MML edges
                for r_mml in alm.remediation_mml:
                    entities_list.append(
                        {
                            "name": r_mml,
                            "entity_type": "mml_command",
                            "normalized_name": r_mml.lower(),
                            "context": f"Remediation MML for {alm.alarm_id}",
                            "clearance_level": clr_int,
                        }
                    )
                    relations_list.append(
                        {
                            "source": alm.alarm_id,
                            "target": r_mml,
                            "relation_type": "REMEDIATED_BY_MML",
                            "source_type": "telecom_alarm",
                            "target_type": "mml_command",
                            "clearance_level": clr_int,
                        }
                    )

                # Add HAS_DIAGRAM edges for ladder/architecture/mechanism diagrams
                for diag_uri in alm.diagram_uris:
                    entities_list.append(
                        {
                            "name": diag_uri,
                            "entity_type": "telecom_diagram",
                            "normalized_name": diag_uri.lower(),
                            "context": f"Diagram for {alm.alarm_id}",
                            "clearance_level": clr_int,
                        }
                    )
                    relations_list.append(
                        {
                            "source": alm.alarm_id,
                            "target": diag_uri,
                            "relation_type": "HAS_DIAGRAM",
                            "source_type": "telecom_alarm",
                            "target_type": "telecom_diagram",
                            "clearance_level": clr_int,
                        }
                    )

                graph_store.index_document(
                    corpus="hdx_telecom",
                    doc_identifier=alm.alarm_id,
                    title=f"{alm.alarm_id}: {alm.alarm_name}",
                    url=alm.virtual_uri,
                    entities=entities_list,
                    relations=relations_list,
                    clearance_level=clr_int,
                )
                indexed_graph_edges += len(relations_list)

        total_ingest_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "status": "success",
            "archive_path": manifest.archive_path,
            "package_title": manifest.package_title,
            "version": manifest.version,
            "total_entries": manifest.total_entries,
            "alarms_extracted": len(manifest.alarms),
            "mml_commands_extracted": len(manifest.mml_commands),
            "kpi_counters_extracted": len(manifest.kpi_counters),
            "raptor_nodes_built": len(manifest.raptor_nodes),
            "indexed_router_records": indexed_router_records,
            "indexed_graph_edges": indexed_graph_edges,
            "parse_latency_ms": manifest.parse_latency_ms,
            "total_ingest_latency_ms": total_ingest_ms,
            "manifest": manifest,
        }
