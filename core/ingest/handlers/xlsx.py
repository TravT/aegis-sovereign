"""
Excel (.xlsx / .xlsm / .xltx) handler.

Reads the workbook the way Excel does: sheet order and visibility from `workbook.xml`, shared and
inline strings, cached formula results, and merged ranges (which the shared grid logic expands so
multi-row / merged headers stay attached to every row). One section per sheet, one line per row.
Dates are stored by Excel as serial numbers; they are kept as the raw number (noted in metadata).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register
from .tables import Cells, Merge, fmt_number, grid_to_section
from .xmlutil import guard_xml, local

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_PART_BYTES = 800 * 1024 * 1024
MAX_RATIO = 250
_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _ref(ref: str) -> Tuple[int, int]:
    m = _REF.match(ref)
    if not m:
        raise ValueError(ref)
    return int(m.group(2)), _col_index(m.group(1))


def _shared_strings(zf: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out: List[str] = []
    with zf.open("xl/sharedStrings.xml") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if local(el.tag) == "si":
                parts: List[str] = []
                for ch in el:  # plain <t> and rich <r><t>; phonetic <rPh> runs are skipped
                    tag = local(ch.tag)
                    if tag == "t":
                        parts.append(ch.text or "")
                    elif tag == "r":
                        parts.append("".join(x.text or "" for x in ch.iter(f"{NS}t")))
                out.append("".join(parts))
                el.clear()
    return out


def _sheet_list(zf: zipfile.ZipFile) -> List[Tuple[str, str, bool]]:
    """[(sheet name, part path, hidden)] in workbook order."""
    wb = ET.fromstring(guard_xml(zf.read("xl/workbook.xml")))
    rels: Dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in zf.namelist():
        for r in ET.fromstring(guard_xml(zf.read("xl/_rels/workbook.xml.rels"))):
            rels[r.get("Id", "")] = r.get("Target", "")
    out: List[Tuple[str, str, bool]] = []
    for sh in wb.iter(f"{NS}sheet"):
        target = rels.get(sh.get(f"{RNS}id", ""), "")
        if not target:
            continue
        part = target.lstrip("/") if target.startswith("/") else "xl/" + target
        out.append((sh.get("name", "sheet"), part, sh.get("state", "visible") != "visible"))
    return out


def _read_sheet(zf: zipfile.ZipFile, part: str, sst: List[str]) -> Tuple[Cells, List[Merge]]:
    cells: Cells = {}
    merges: List[Merge] = []
    with zf.open(part) as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            tag = local(el.tag)
            if tag == "c":
                ref, t = el.get("r"), el.get("t")
                if ref:
                    v = el.find(f"{NS}v")
                    text = ""
                    if t == "s" and v is not None and (v.text or "").isdigit():
                        i = int(v.text)
                        text = sst[i] if i < len(sst) else ""
                    elif t == "inlineStr":
                        text = "".join(x.text or "" for x in el.iter(f"{NS}t"))
                    elif t in ("str", "e") and v is not None:
                        text = v.text or ""
                    elif t == "b" and v is not None:
                        text = "TRUE" if (v.text or "") == "1" else "FALSE"
                    elif v is not None and v.text:
                        try:
                            text = fmt_number(float(v.text))
                        except ValueError:
                            text = v.text
                    if text.strip():
                        try:
                            cells[_ref(ref)] = text
                        except ValueError:
                            pass
                el.clear()
            elif tag == "mergeCell":
                rng = el.get("ref", "")
                if ":" in rng:
                    try:
                        (r1, c1), (r2, c2) = (_ref(x) for x in rng.split(":", 1))
                        merges.append((r1, c1, r2, c2))
                    except ValueError:
                        pass
    return cells, merges


@register
class XlsxHandler(FormatHandler):
    name = "xlsx"
    version = "1"
    extensions = (".xlsx", ".xlsm", ".xltx")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            zf.getinfo("xl/workbook.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise HandlerError(f"not a readable .xlsx: {exc}") from exc
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        try:
            sst = _shared_strings(zf)
            for sheet, part, hidden in _sheet_list(zf):
                if part not in zf.namelist():
                    doc.warnings.append(f"sheet {sheet!r}: part {part} missing")
                    continue
                info = zf.getinfo(part)
                if info.file_size > MAX_PART_BYTES or (info.compress_size and info.file_size / info.compress_size > MAX_RATIO):
                    raise HandlerError(f"sheet {sheet!r} exceeds the size / compression-ratio guard")
                cells, merges = _read_sheet(zf, part, sst)
                section = grid_to_section(sheet, cells, merges)
                if section is not None:
                    doc.sections.append(section)
                if hidden:
                    doc.warnings.append(f"sheet {sheet!r} is hidden (indexed anyway)")
        except ET.ParseError as exc:
            raise HandlerError(f"malformed workbook XML: {exc}") from exc
        doc.metadata["sheets"] = str(len(doc.sections))
        doc.metadata["dates"] = "stored as raw Excel serial numbers"
        return doc
