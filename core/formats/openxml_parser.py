#!/usr/bin/env python3
"""In-Memory OpenXML (.xlsx / .xlsm / .docx) Telecom ReleaseDoc Parser & Ingestor.

Pure Python stdlib (`zipfile` + `xml.etree.ElementTree` + `io.BytesIO`) parser
for Huawei/3GPP `.xlsx` / `.xlsm` adaptation workbooks (`Alarm List.xlsx`,
`Event List.xlsx`, `Performance Counter List.xlsx`) and `.docx` engineering
manuals (`Patch Installation Guide.docx`, `Upgrade Guide.docx`, `Patch Notes.docx`).

Enforces ADR-07 security invariants:
- 100% in-memory `io.BytesIO` streaming (zero temporary files on disk).
- Strict XXE / XML entity expansion guardrails.
- Direct indexing into `SovereignQueryRouter` (Prong 1 B-Tree + FTS5) and
  `GraphStore` (Prong 2 multi-hop relational edges).
"""

from __future__ import annotations

import io
import os
import posixpath
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.containers.archive_streamer import (
    ArchiveSecurityError,
    SovereignArchiveStreamer,
)
from core.containers.hdx_parser import (
    ALARM_ID_RE,
    KPI_COUNTER_RE,
    MML_COMMAND_RE,
    NE_NAME_RE,
    _XXE_GUARD_RE,
    _normalize_cause_token,
)
from core.security import ClearanceLevel

_CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")

_ALARM_LEVEL_MAP = {
    "1": "Critical",
    "2": "Major",
    "3": "Minor",
    "4": "Warning",
    "critical": "Critical",
    "major": "Major",
    "minor": "Minor",
    "warning": "Warning",
}


def _col_letters_to_index(col_letters: str) -> int:
    """Convert Excel column letters ('A' -> 0, 'B' -> 1, 'AA' -> 26) to 0-based index."""
    idx = 0
    for ch in col_letters.upper():
        if "A" <= ch <= "Z":
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


@dataclass
class OpenXmlAlarmRecord:
    """Alarm or Event specification row parsed from an OpenXML .xlsx adaptation sheet."""

    alarm_id: str
    raw_id: str
    alarm_name: str
    severity: str
    alarm_type: str
    affected_ne: str
    location_info: str
    explanation: str
    revise_advice: str
    impact_on_system: str
    possible_causes: List[str]
    virtual_uri: str
    sheet_name: str
    record_kind: str = "alarm"  # "alarm" or "event"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alarm_id": self.alarm_id,
            "raw_id": self.raw_id,
            "alarm_name": self.alarm_name,
            "severity": self.severity,
            "alarm_type": self.alarm_type,
            "affected_ne": self.affected_ne,
            "location_info": self.location_info,
            "explanation": self.explanation,
            "revise_advice": self.revise_advice,
            "impact_on_system": self.impact_on_system,
            "possible_causes": self.possible_causes,
            "virtual_uri": self.virtual_uri,
            "sheet_name": self.sheet_name,
            "record_kind": self.record_kind,
        }


@dataclass
class OpenXmlCounterRecord:
    """Performance Counter specification row parsed from an OpenXML .xlsx adaptation sheet."""

    counter_id: str
    counter_name: str
    object_name: str
    function_set_name: str
    function_subset_name: str
    unit: str
    formula: str
    affected_ne: str
    virtual_uri: str
    sheet_name: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counter_id": self.counter_id,
            "counter_name": self.counter_name,
            "object_name": self.object_name,
            "function_set_name": self.function_set_name,
            "function_subset_name": self.function_subset_name,
            "unit": self.unit,
            "formula": self.formula,
            "affected_ne": self.affected_ne,
            "virtual_uri": self.virtual_uri,
            "sheet_name": self.sheet_name,
        }


@dataclass
class OpenXmlDocSection:
    """Structured section and procedure tables extracted from a .docx manual."""

    section_id: str
    title: str
    paragraphs: List[str]
    tables: List[List[List[str]]]
    referenced_alarms: List[str]
    referenced_mml: List[str]
    virtual_uri: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "paragraphs": self.paragraphs,
            "tables": self.tables,
            "referenced_alarms": self.referenced_alarms,
            "referenced_mml": self.referenced_mml,
            "virtual_uri": self.virtual_uri,
        }


@dataclass
class OpenXmlReleaseManifest:
    """Aggregated manifest parsed from `.xlsx`, `.xlsm`, `.docx`, or ReleaseDoc `.zip`."""

    source_path: str
    alarms: List[OpenXmlAlarmRecord] = field(default_factory=list)
    events: List[OpenXmlAlarmRecord] = field(default_factory=list)
    counters: List[OpenXmlCounterRecord] = field(default_factory=list)
    doc_sections: List[OpenXmlDocSection] = field(default_factory=list)
    parse_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "alarms": [a.to_dict() for a in self.alarms],
            "events": [e.to_dict() for e in self.events],
            "counters": [c.to_dict() for c in self.counters],
            "doc_sections": [s.to_dict() for s in self.doc_sections],
            "parse_latency_ms": self.parse_latency_ms,
        }


class OpenXmlReleaseDocParser:
    """Pure Python stdlib in-memory parser for `.xlsx`, `.xlsm`, and `.docx` telecom docs."""

    def __init__(self, streamer: Optional[SovereignArchiveStreamer] = None) -> None:
        self.streamer = streamer or SovereignArchiveStreamer()

    @staticmethod
    def _detect_ne_from_label(label: str) -> str:
        """Infer Network Element name (e.g. UPCF, USCDB, CSP, USC) from filename or sheet."""
        m = NE_NAME_RE.search(label)
        if m:
            return m.group(1).upper()
        for candidate in ("UPCF", "USCDB", "CSP", "USC", "UDG", "BBU5900"):
            if candidate.lower() in label.lower():
                return candidate
        return "UPCF"

    def parse_xlsx_bytes(
        self,
        raw_bytes: bytes,
        source_uri_prefix: str,
        default_ne: Optional[str] = None,
        max_rows_per_sheet: int = 5000,
    ) -> Tuple[List[OpenXmlAlarmRecord], List[OpenXmlAlarmRecord], List[OpenXmlCounterRecord]]:
        """Parse an OpenXML `.xlsx` / `.xlsm` workbook purely in memory (`io.BytesIO`)."""
        ne_name = default_ne or self._detect_ne_from_label(source_uri_prefix)
        is_event_workbook = "event list" in source_uri_prefix.lower()

        alarms: List[OpenXmlAlarmRecord] = []
        events: List[OpenXmlAlarmRecord] = []
        counters: List[OpenXmlCounterRecord] = []

        with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
            for info in zf.infolist():
                self.streamer._validate_entry_path(info.filename)

            # 1. Parse xl/sharedStrings.xml if present
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                ss_xml = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
                if _XXE_GUARD_RE.search(ss_xml):
                    raise ArchiveSecurityError("XXE or entity expansion blocked in xl/sharedStrings.xml")
                ss_root = ET.fromstring(ss_xml)
                for elem in ss_root.iter():
                    if elem.tag.endswith("}si") or elem.tag == "si":
                        shared_strings.append("".join(elem.itertext()))

            # 2. Map sheet names to worksheet XML files via xl/workbook.xml + xl/_rels/workbook.xml.rels
            sheet_entries: List[Tuple[str, str]] = []
            if "xl/workbook.xml" in zf.namelist():
                wb_xml = zf.read("xl/workbook.xml").decode("utf-8", errors="replace")
                if _XXE_GUARD_RE.search(wb_xml):
                    raise ArchiveSecurityError("XXE or entity expansion blocked in xl/workbook.xml")
                wb_root = ET.fromstring(wb_xml)

                rel_map: Dict[str, str] = {}
                if "xl/_rels/workbook.xml.rels" in zf.namelist():
                    rels_xml = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", errors="replace")
                    rels_root = ET.fromstring(rels_xml)
                    for rel_el in rels_root.iter():
                        if rel_el.tag.endswith("Relationship"):
                            r_id = rel_el.attrib.get("Id", "")
                            target = rel_el.attrib.get("Target", "").lstrip("/")
                            if not target.startswith("xl/"):
                                target = posixpath.normpath(posixpath.join("xl", target))
                            rel_map[r_id] = target

                sheet_idx = 1
                for sh_el in wb_root.iter():
                    if sh_el.tag.endswith("}sheet") or sh_el.tag == "sheet":
                        sh_name = sh_el.attrib.get("name") or f"Sheet{sheet_idx}"
                        r_id = ""
                        for k, v in sh_el.attrib.items():
                            if k.endswith("}id") or k == "r:id":
                                r_id = v
                                break
                        target_path = rel_map.get(r_id) or f"xl/worksheets/sheet{sheet_idx}.xml"
                        if target_path in zf.namelist():
                            sheet_entries.append((sh_name, target_path))
                        sheet_idx += 1

            if not sheet_entries:
                for name in sorted(zf.namelist()):
                    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                        sheet_entries.append((Path(name).stem, name))

            # 3. Parse each worksheet grid
            for sheet_name, sheet_xml_path in sheet_entries:
                sh_xml = zf.read(sheet_xml_path).decode("utf-8", errors="replace")
                if _XXE_GUARD_RE.search(sh_xml):
                    raise ArchiveSecurityError(f"XXE or entity expansion blocked in {sheet_xml_path}")
                sh_root = ET.fromstring(sh_xml)

                rows_grid: List[List[str]] = []
                row_count = 0
                for row_el in sh_root.iter():
                    if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
                        continue
                    row_count += 1
                    if row_count > max_rows_per_sheet:
                        break

                    cell_map: Dict[int, str] = {}
                    max_col = -1
                    next_col = 0
                    for c_el in row_el:
                        if not (c_el.tag.endswith("}c") or c_el.tag == "c"):
                            continue
                        ref = c_el.attrib.get("r", "")
                        m_ref = _CELL_REF_RE.match(ref)
                        col_idx = _col_letters_to_index(m_ref.group(1)) if m_ref else next_col
                        next_col = col_idx + 1
                        max_col = max(max_col, col_idx)

                        c_type = c_el.attrib.get("t", "")
                        val_str = ""
                        if c_type == "inlineStr":
                            val_str = "".join(c_el.itertext()).strip()
                        else:
                            for child in c_el:
                                if child.tag.endswith("}v") or child.tag == "v":
                                    raw_v = (child.text or "").strip()
                                    if c_type == "s" and raw_v.isdigit():
                                        s_idx = int(raw_v)
                                        if 0 <= s_idx < len(shared_strings):
                                            val_str = shared_strings[s_idx].strip()
                                    else:
                                        val_str = raw_v
                                    break
                        if val_str:
                            cell_map[col_idx] = val_str

                    if max_col >= 0 and cell_map:
                        row_list = [cell_map.get(i, "") for i in range(max_col + 1)]
                        rows_grid.append(row_list)

                if len(rows_grid) < 2:
                    continue

                # Locate header row within the first 5 rows
                header_row_idx = -1
                header_map: Dict[str, int] = {}
                for r_idx in range(min(5, len(rows_grid))):
                    candidate_headers = {
                        re.sub(r"\s+", " ", cell.strip().lower()): c_i
                        for c_i, cell in enumerate(rows_grid[r_idx])
                        if cell.strip()
                    }
                    if any(
                        k in candidate_headers
                        for k in ("alarmid", "alarm id", "eventid", "event id", "counter id", "counterid")
                    ):
                        header_row_idx = r_idx
                        header_map = candidate_headers
                        break

                if header_row_idx < 0:
                    continue

                vuri = f"{source_uri_prefix}#{sheet_xml_path}"

                # Case A: Alarm List or Event List sheet
                if any(k in header_map for k in ("alarmid", "alarm id", "eventid", "event id")):
                    id_col = (
                        header_map.get("alarmid")
                        if "alarmid" in header_map
                        else header_map.get(
                            "alarm id",
                            header_map.get("eventid", header_map.get("event id", 0)),
                        )
                    )
                    name_col = header_map.get(
                        "alarmname",
                        header_map.get("alarm name", header_map.get("eventname", header_map.get("event name", 1))),
                    )
                    level_col = header_map.get(
                        "alarmlevel",
                        header_map.get("alarm level", header_map.get("alarm severity", header_map.get("eventlevel", 2))),
                    )
                    type_col = header_map.get("alarmtype", header_map.get("alarm type", 3))
                    loc_col = header_map.get("location information", 4)
                    exp_col = header_map.get("alarm explain", header_map.get("description", 5))
                    adv_col = header_map.get("revise advice", header_map.get("handling procedure", 6))
                    imp_col = header_map.get("impact on the system", 7)
                    cause_col = header_map.get("possible causes", 9)

                    is_event = (
                        is_event_workbook
                        or "event" in sheet_name.lower()
                        or "eventid" in header_map
                        or "event id" in header_map
                    )

                    for data_row in rows_grid[header_row_idx + 1 :]:
                        raw_id = data_row[id_col].strip() if id_col < len(data_row) else ""
                        if not raw_id:
                            continue
                        if raw_id.upper().startswith(("ALM-", "EVT-")):
                            canonical_id = raw_id.upper()
                        elif re.fullmatch(r"\d{3,8}", raw_id):
                            prefix = "EVT" if is_event else "ALM"
                            canonical_id = f"{prefix}-{raw_id}"
                        else:
                            continue

                        a_name = data_row[name_col].strip() if name_col < len(data_row) else canonical_id
                        raw_lvl = data_row[level_col].strip() if level_col < len(data_row) else "Major"
                        severity = _ALARM_LEVEL_MAP.get(raw_lvl.lower(), raw_lvl or "Major")
                        a_type = data_row[type_col].strip() if type_col < len(data_row) else ""
                        loc_info = data_row[loc_col].strip() if loc_col < len(data_row) else ""
                        explain = data_row[exp_col].strip() if exp_col < len(data_row) else a_name
                        advice = data_row[adv_col].strip() if adv_col < len(data_row) else ""
                        impact = data_row[imp_col].strip() if imp_col < len(data_row) else ""
                        raw_causes = data_row[cause_col].strip() if cause_col < len(data_row) else ""
                        causes_list = [
                            c.strip()
                            for c in re.split(r"[;\n]+", raw_causes)
                            if c.strip() and c.strip().lower() != "none"
                        ]
                        if not causes_list:
                            causes_list = [a_name]

                        rec = OpenXmlAlarmRecord(
                            alarm_id=canonical_id,
                            raw_id=raw_id,
                            alarm_name=a_name,
                            severity=severity,
                            alarm_type=a_type,
                            affected_ne=ne_name,
                            location_info=loc_info,
                            explanation=explain,
                            revise_advice=advice,
                            impact_on_system=impact,
                            possible_causes=causes_list,
                            virtual_uri=vuri,
                            sheet_name=sheet_name,
                            record_kind="event" if is_event else "alarm",
                        )
                        if is_event:
                            events.append(rec)
                        else:
                            alarms.append(rec)

                # Case B: Performance Counter List sheet
                elif any(k in header_map for k in ("counter id", "counterid")):
                    cid_col = header_map.get("counter id", header_map.get("counterid", 7))
                    cname_col = header_map.get("counter name", header_map.get("countername", 8))
                    obj_col = header_map.get("object name", header_map.get("objectname", 6))
                    fset_col = header_map.get("functionset name", 1)
                    fsub_col = header_map.get("functionsubset name", 3)
                    unit_col = header_map.get("counter unit", header_map.get("unit", 9))
                    form_col = header_map.get("formula", 14)
                    ne_col = header_map.get("ne", -1)

                    for data_row in rows_grid[header_row_idx + 1 :]:
                        cid = data_row[cid_col].strip() if cid_col < len(data_row) else ""
                        if not cid:
                            continue
                        cname = data_row[cname_col].strip() if cname_col < len(data_row) else cid
                        obj_name = data_row[obj_col].strip() if obj_col < len(data_row) else ne_name
                        fset = data_row[fset_col].strip() if fset_col < len(data_row) else ""
                        fsub = data_row[fsub_col].strip() if fsub_col < len(data_row) else ""
                        unit = data_row[unit_col].strip() if unit_col < len(data_row) else "times"
                        formula = data_row[form_col].strip() if form_col < len(data_row) else "None"
                        row_ne = (
                            data_row[ne_col].strip()
                            if 0 <= ne_col < len(data_row) and data_row[ne_col].strip()
                            else ne_name
                        )

                        counters.append(
                            OpenXmlCounterRecord(
                                counter_id=cid,
                                counter_name=cname,
                                object_name=obj_name,
                                function_set_name=fset,
                                function_subset_name=fsub,
                                unit=unit,
                                formula=formula,
                                affected_ne=row_ne,
                                virtual_uri=vuri,
                                sheet_name=sheet_name,
                            )
                        )

        return alarms, events, counters

    def parse_docx_bytes(
        self,
        raw_bytes: bytes,
        source_uri_prefix: str,
        doc_title_fallback: str = "Release Manual",
    ) -> List[OpenXmlDocSection]:
        """Parse an OpenXML `.docx` document (`word/document.xml`) purely in memory (`io.BytesIO`)."""
        sections: List[OpenXmlDocSection] = []

        with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as zf:
            for info in zf.infolist():
                self.streamer._validate_entry_path(info.filename)
            if "word/document.xml" not in zf.namelist():
                return sections
            doc_xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
            if _XXE_GUARD_RE.search(doc_xml):
                raise ArchiveSecurityError("XXE or entity expansion blocked in word/document.xml")

        root = ET.fromstring(doc_xml)
        body = None
        for el in root:
            if el.tag.endswith("}body") or el.tag == "body":
                body = el
                break
        if body is None:
            body = root

        current_title = doc_title_fallback
        current_paragraphs: List[str] = []
        current_tables: List[List[List[str]]] = []
        sec_counter = 1

        def _flush_section() -> None:
            nonlocal sec_counter, current_paragraphs, current_tables
            if not current_paragraphs and not current_tables:
                return
            joined_text = "\n".join(current_paragraphs)
            for tbl in current_tables:
                for row in tbl:
                    joined_text += "\n" + " | ".join(row)

            ref_alarms = list(dict.fromkeys(m.upper() for m in ALARM_ID_RE.findall(joined_text)))
            ref_mml = list(dict.fromkeys(m.upper() for m in MML_COMMAND_RE.findall(joined_text)))
            slug = re.sub(r"[^A-Za-z0-9]+", "-", current_title[:36]).strip("-").upper() or f"SEC-{sec_counter}"
            sec_id = f"DOCX-{sec_counter:02d}-{slug}"
            sections.append(
                OpenXmlDocSection(
                    section_id=sec_id,
                    title=current_title,
                    paragraphs=list(current_paragraphs),
                    tables=list(current_tables),
                    referenced_alarms=ref_alarms,
                    referenced_mml=ref_mml,
                    virtual_uri=f"{source_uri_prefix}#word/document.xml",
                )
            )
            sec_counter += 1
            current_paragraphs = []
            current_tables = []

        for child in body:
            if child.tag.endswith("}p") or child.tag == "p":
                is_heading = False
                for p_child in child.iter():
                    if p_child.tag.endswith("}pStyle") or p_child.tag == "pStyle":
                        for attr_k, attr_v in p_child.attrib.items():
                            if (attr_k.endswith("}val") or attr_k == "val") and "heading" in attr_v.lower():
                                is_heading = True
                                break
                text = "".join(child.itertext()).strip()
                if not text:
                    continue
                if is_heading and (current_paragraphs or current_tables):
                    _flush_section()
                    current_title = text
                elif is_heading:
                    current_title = text
                else:
                    current_paragraphs.append(text)

            elif child.tag.endswith("}tbl") or child.tag == "tbl":
                tbl_rows: List[List[str]] = []
                for tr in child:
                    if not (tr.tag.endswith("}tr") or tr.tag == "tr"):
                        continue
                    row_cells: List[str] = []
                    for tc in tr:
                        if not (tc.tag.endswith("}tc") or tc.tag == "tc"):
                            continue
                        cell_text = " ".join(
                            t.strip() for t in "".join(tc.itertext()).splitlines() if t.strip()
                        )
                        row_cells.append(cell_text)
                    if any(row_cells):
                        tbl_rows.append(row_cells)
                if tbl_rows:
                    current_tables.append(tbl_rows)

        _flush_section()
        return sections

    def parse_release_package(
        self,
        package_path: Union[str, Path],
        max_rows_per_sheet: int = 5000,
    ) -> OpenXmlReleaseManifest:
        """Stream and parse a `.xlsx`, `.xlsm`, `.docx`, or a `.zip` containing OpenXML ReleaseDocs."""
        t0 = time.perf_counter()
        path_obj = Path(package_path)
        path_str = str(package_path)
        lower_name = path_obj.name.lower()

        raw_bytes = self.streamer._read_file_readonly_bytes(path_obj)
        manifest = OpenXmlReleaseManifest(source_path=path_str)

        if lower_name.endswith((".xlsx", ".xlsm")):
            vuri_prefix = f"archive://{path_str}"
            alarms, events, counters = self.parse_xlsx_bytes(
                raw_bytes=raw_bytes,
                source_uri_prefix=vuri_prefix,
                max_rows_per_sheet=max_rows_per_sheet,
            )
            manifest.alarms.extend(alarms)
            manifest.events.extend(events)
            manifest.counters.extend(counters)

        elif lower_name.endswith(".docx"):
            vuri_prefix = f"archive://{path_str}"
            sections = self.parse_docx_bytes(
                raw_bytes=raw_bytes,
                source_uri_prefix=vuri_prefix,
                doc_title_fallback=path_obj.stem,
            )
            manifest.doc_sections.extend(sections)

        elif lower_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r") as outer_zf:
                for info in outer_zf.infolist():
                    self.streamer._validate_entry_path(info.filename)
                    if info.is_dir() or info.filename.endswith("/"):
                        continue
                    lower_member = info.filename.lower()
                    if lower_member.endswith((".xlsx", ".xlsm")):
                        member_bytes = self.streamer._read_member_bytes_bounded(
                            zf=outer_zf,
                            info=info,
                            max_bytes=self.streamer.max_entry_bytes,
                        )
                        vuri_prefix = f"archive://{path_str}!{info.filename}"
                        alarms, events, counters = self.parse_xlsx_bytes(
                            raw_bytes=member_bytes,
                            source_uri_prefix=vuri_prefix,
                            default_ne=self._detect_ne_from_label(info.filename),
                            max_rows_per_sheet=max_rows_per_sheet,
                        )
                        manifest.alarms.extend(alarms)
                        manifest.events.extend(events)
                        manifest.counters.extend(counters)
                    elif lower_member.endswith(".docx"):
                        member_bytes = self.streamer._read_member_bytes_bounded(
                            zf=outer_zf,
                            info=info,
                            max_bytes=self.streamer.max_entry_bytes,
                        )
                        vuri_prefix = f"archive://{path_str}!{info.filename}"
                        sections = self.parse_docx_bytes(
                            raw_bytes=member_bytes,
                            source_uri_prefix=vuri_prefix,
                            doc_title_fallback=Path(info.filename).stem,
                        )
                        manifest.doc_sections.extend(sections)

        manifest.parse_latency_ms = (time.perf_counter() - t0) * 1000.0
        return manifest

    def ingest_release_package(
        self,
        package_path: Union[str, Path],
        router: Optional[Any] = None,
        graph_store: Optional[Any] = None,
        clearance_level: Union[str, int, ClearanceLevel] = ClearanceLevel.INTERNAL,
        max_rows_per_sheet: int = 5000,
    ) -> Dict[str, Any]:
        """Parse OpenXML ReleaseDocs in-memory and index Alarms, Events, Counters, and DOCX manuals
        into SovereignQueryRouter (Prong 1) and GraphStore (Prong 2).
        """
        t0 = time.perf_counter()
        manifest = self.parse_release_package(package_path, max_rows_per_sheet=max_rows_per_sheet)
        clr_obj = ClearanceLevel.from_string(clearance_level)
        clr_int = clr_obj.value

        indexed_router_records = 0
        indexed_graph_edges = 0

        if router is not None:
            for alm in manifest.alarms + manifest.events:
                causes_str = "; ".join(alm.possible_causes)
                content_body = (
                    f"[{alm.alarm_id}] {alm.alarm_name} | Severity: {alm.severity} | "
                    f"Affected NE: {alm.affected_ne} | Location: {alm.location_info}\n"
                    f"Explanation: {alm.explanation}\n"
                    f"Possible Causes: {causes_str}\n"
                    f"Impact: {alm.impact_on_system} | Revise Advice: {alm.revise_advice}"
                )
                router.index_document(
                    doc_identifier=alm.alarm_id,
                    title=f"{alm.alarm_id}: {alm.alarm_name} ({alm.severity})",
                    content=content_body,
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": alm.virtual_uri,
                        "entity_type": "telecom_alarm" if alm.record_kind == "alarm" else "telecom_event",
                        "severity": alm.severity,
                        "affected_ne": alm.affected_ne,
                        "possible_causes": alm.possible_causes,
                        "sheet_name": alm.sheet_name,
                    },
                )
                indexed_router_records += 1
                # If event, also index ALM-<raw_id> alias so ALM-\d{3,6} fast-path lookup resolves events too
                if alm.record_kind == "event" and re.fullmatch(r"\d{3,6}", alm.raw_id):
                    alm_alias = f"ALM-{alm.raw_id}"
                    router.index_document(
                        doc_identifier=alm_alias,
                        title=f"{alm.alarm_id} ({alm_alias}): {alm.alarm_name}",
                        content=content_body,
                        clearance_level=clr_obj,
                        metadata={
                            "virtual_uri": alm.virtual_uri,
                            "entity_type": "telecom_event",
                            "canonical_event_id": alm.alarm_id,
                            "affected_ne": alm.affected_ne,
                        },
                    )
                    indexed_router_records += 1

            for ctr in manifest.counters:
                content_body = (
                    f"[Performance Counter: {ctr.counter_id}] {ctr.counter_name} | "
                    f"Object: {ctr.object_name} | FunctionSet: {ctr.function_set_name} ({ctr.function_subset_name}) | "
                    f"Unit: {ctr.unit} | Formula: {ctr.formula} | NE: {ctr.affected_ne}"
                )
                router.index_document(
                    doc_identifier=ctr.counter_id,
                    title=f"Counter {ctr.counter_id}: {ctr.counter_name} ({ctr.object_name})",
                    content=content_body,
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": ctr.virtual_uri,
                        "entity_type": "telecom_kpi",
                        "object_name": ctr.object_name,
                        "function_set_name": ctr.function_set_name,
                        "unit": ctr.unit,
                        "formula": ctr.formula,
                        "affected_ne": ctr.affected_ne,
                    },
                )
                indexed_router_records += 1

            for sec in manifest.doc_sections:
                body_preview = "\n".join(sec.paragraphs[:15])
                router.index_document(
                    doc_identifier=sec.section_id,
                    title=f"Manual Section: {sec.title}",
                    content=f"[{sec.title}]\n{body_preview}",
                    clearance_level=clr_obj,
                    metadata={
                        "virtual_uri": sec.virtual_uri,
                        "entity_type": "release_doc_section",
                        "referenced_alarms": sec.referenced_alarms,
                        "referenced_mml": sec.referenced_mml,
                    },
                )
                indexed_router_records += 1

        if graph_store is not None:
            for alm in manifest.alarms + manifest.events:
                entities = [
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
                        "context": f"Affected NE for {alm.alarm_id}",
                        "clearance_level": clr_int,
                    },
                ]
                relations = [
                    {
                        "source": alm.alarm_id,
                        "target": alm.affected_ne,
                        "relation_type": "AFFECTS_NE",
                        "source_type": "telecom_alarm",
                        "target_type": "network_element",
                        "clearance_level": clr_int,
                    }
                ]
                for cause in alm.possible_causes[:4]:
                    cause_tok = _normalize_cause_token(cause)
                    entities.append(
                        {
                            "name": cause_tok,
                            "entity_type": "alarm_cause",
                            "normalized_name": cause_tok.lower(),
                            "context": cause,
                            "clearance_level": clr_int,
                        }
                    )
                    relations.append(
                        {
                            "source": alm.alarm_id,
                            "target": cause_tok,
                            "relation_type": "CAUSED_BY",
                            "source_type": "telecom_alarm",
                            "target_type": "alarm_cause",
                            "clearance_level": clr_int,
                        }
                    )
                graph_store.index_document(
                    corpus="openxml_telecom",
                    doc_identifier=alm.alarm_id,
                    title=f"{alm.alarm_id}: {alm.alarm_name}",
                    url=alm.virtual_uri,
                    entities=entities,
                    relations=relations,
                    clearance_level=clr_int,
                )
                indexed_graph_edges += len(relations)

            for ctr in manifest.counters[:500]:
                entities = [
                    {
                        "name": ctr.counter_id,
                        "entity_type": "telecom_kpi",
                        "normalized_name": ctr.counter_id.lower(),
                        "context": ctr.counter_name,
                        "clearance_level": clr_int,
                    },
                    {
                        "name": ctr.object_name,
                        "entity_type": "performance_object",
                        "normalized_name": ctr.object_name.lower(),
                        "context": ctr.function_set_name,
                        "clearance_level": clr_int,
                    },
                ]
                relations = [
                    {
                        "source": ctr.counter_id,
                        "target": ctr.object_name,
                        "relation_type": "MEASURES_OBJECT",
                        "source_type": "telecom_kpi",
                        "target_type": "performance_object",
                        "clearance_level": clr_int,
                    }
                ]
                graph_store.index_document(
                    corpus="openxml_telecom",
                    doc_identifier=ctr.counter_id,
                    title=f"Counter {ctr.counter_id}: {ctr.counter_name}",
                    url=ctr.virtual_uri,
                    entities=entities,
                    relations=relations,
                    clearance_level=clr_int,
                )
                indexed_graph_edges += len(relations)

        return {
            "status": "success",
            "source_path": manifest.source_path,
            "alarms_extracted": len(manifest.alarms),
            "events_extracted": len(manifest.events),
            "counters_extracted": len(manifest.counters),
            "doc_sections_extracted": len(manifest.doc_sections),
            "indexed_router_records": indexed_router_records,
            "indexed_graph_edges": indexed_graph_edges,
            "parse_latency_ms": manifest.parse_latency_ms,
            "total_ingest_latency_ms": (time.perf_counter() - t0) * 1000.0,
            "manifest": manifest,
        }
