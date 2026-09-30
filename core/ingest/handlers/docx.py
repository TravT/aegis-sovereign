"""
Word (.docx / .docm / .dotx) handler.

Structure comes from the document's own paragraph styles:
  * heading level = style name "heading N" (resolved through `styles.xml`, following `basedOn`),
    or an explicit outline level on the style / paragraph; "TableHeading", "NotesHeading" and
    other look-alikes are NOT headings;
  * body content is read in order: paragraphs and tables (a row becomes `cell | cell | cell`);
  * table-of-contents paragraphs are skipped (they only repeat the headings);
  * footnotes are appended as a final section; embedded images are counted, not indexed.
The XML is streamed, so very large manuals do not need a full in-memory tree.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List, Optional, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register
from .xmlutil import guard_xml, local

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_PART_BYTES = 400 * 1024 * 1024  # uncompressed size of word/document.xml we are willing to read
MAX_RATIO = 250

_HEADING_NAME = re.compile(r"^heading\s*(\d)\b", re.IGNORECASE)
_HEADING_ID = re.compile(r"^Heading(\d)(?!\w*(?:Table|Notes))", re.IGNORECASE)


def _styles(zf: zipfile.ZipFile) -> Dict[str, Tuple[str, Optional[str], Optional[int]]]:
    """styleId -> (lower-case name, basedOn id, outline level 1..9 or None)."""
    out: Dict[str, Tuple[str, Optional[str], Optional[int]]] = {}
    if "word/styles.xml" not in zf.namelist():
        return out
    root = ET.fromstring(guard_xml(zf.read("word/styles.xml")))
    for st in root.iter(f"{W}style"):
        sid = st.get(f"{W}styleId")
        if not sid or st.get(f"{W}type") not in (None, "paragraph"):
            continue
        name_el, based_el = st.find(f"{W}name"), st.find(f"{W}basedOn")
        lvl_el = st.find(f"{W}pPr/{W}outlineLvl")
        lvl = int(lvl_el.get(f"{W}val")) + 1 if lvl_el is not None and lvl_el.get(f"{W}val", "").isdigit() else None
        out[sid] = (
            (name_el.get(f"{W}val", "") if name_el is not None else "").lower(),
            based_el.get(f"{W}val") if based_el is not None else None,
            lvl if lvl and lvl <= 9 else None,
        )
    return out


def _heading_level(style_id: Optional[str], styles: Dict, own_outline: Optional[int]) -> Optional[int]:
    if own_outline:
        return own_outline
    sid, hops = style_id, 0
    while sid and hops < 6:
        name, based, outline = styles.get(sid, ("", None, None))
        m = _HEADING_NAME.match(name)
        if m:
            return int(m.group(1))
        if outline:
            return outline
        if not name and (mid := _HEADING_ID.match(sid)):
            return int(mid.group(1))
        sid, hops = based, hops + 1
    return None


def _is_toc(style_id: Optional[str], styles: Dict) -> bool:
    name = styles.get(style_id or "", ("", None, None))[0]
    return (style_id or "").lower().startswith("toc") or name.startswith("toc") or name == "table of contents"


def _text(el: ET.Element) -> str:
    """Visible text of an element in reading order (skips field codes, deletions and duplicate fallbacks)."""
    out: List[str] = []

    def walk(node: ET.Element) -> None:
        for ch in node:
            t = local(ch.tag)
            if t in ("instrText", "delText", "Fallback"):
                continue
            if t == "t":
                out.append(ch.text or "")
            elif t == "tab":
                out.append("\t")
            elif t in ("br", "cr"):
                out.append("\n")
            elif t == "noBreakHyphen":
                out.append("-")
            else:
                walk(ch)

    walk(el)
    return "".join(out)


def _table_lines(tbl: ET.Element) -> List[str]:
    lines: List[str] = []
    for tr in tbl.iter(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            cells.append(" ".join(t.strip() for t in (_text(p) for p in tc.iter(f"{W}p")) if t.strip()))
        if any(c for c in cells):
            lines.append(" | ".join(cells))
    return lines


@register
class DocxHandler(FormatHandler):
    name = "docx"
    version = "1"
    extensions = (".docx", ".docm", ".dotx")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            info = zf.getinfo("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise HandlerError(f"not a readable .docx: {exc}") from exc
        if info.file_size > MAX_PART_BYTES or (info.compress_size and info.file_size / info.compress_size > MAX_RATIO):
            raise HandlerError("word/document.xml exceeds the size / compression-ratio guard")
        styles = _styles(zf)
        title = self.title_from(name)
        doc = ParsedDocument(name=name, format=self.name, title=title)
        if "docProps/core.xml" in zf.namelist():
            m = re.search(rb"<dc:title>([^<]+)</dc:title>", zf.read("docProps/core.xml"))
            if m:
                doc.metadata["title"] = m.group(1).decode("utf-8", "ignore").strip()

        stack: List[Tuple[int, str]] = []
        lines: List[str] = []
        sections: List[Section] = []

        def flush() -> None:
            text = "\n".join(lines).strip("\n")
            if text.strip():
                sections.append(Section(tuple(t for _, t in stack), text))
            lines.clear()

        def handle(el: ET.Element) -> None:
            tag = local(el.tag)
            if tag == "p":
                ppr = el.find(f"{W}pPr")
                sid = own = None
                if ppr is not None:
                    ps = ppr.find(f"{W}pStyle")
                    sid = ps.get(f"{W}val") if ps is not None else None
                    ol = ppr.find(f"{W}outlineLvl")
                    own = int(ol.get(f"{W}val")) + 1 if ol is not None and ol.get(f"{W}val", "").isdigit() else None
                    own = own if own and own <= 9 else None
                if _is_toc(sid, styles):
                    return
                text = _text(el).strip()
                if not text:
                    return
                lvl = _heading_level(sid, styles, own)
                if lvl:
                    flush()
                    while stack and stack[-1][0] >= lvl:
                        stack.pop()
                    stack.append((lvl, " ".join(text.split())))
                else:
                    lines.append(text)
            elif tag == "tbl":
                lines.extend(_table_lines(el))
            elif tag == "sdt":  # content controls wrap real body content (and the table of contents)
                content = el.find(f"{W}sdtContent")
                if content is not None:
                    for ch in content:
                        handle(ch)

        depth = 0
        with zf.open(info) as fh:
            try:
                for event, el in ET.iterparse(fh, events=("start", "end")):
                    if event == "start":
                        depth += 1
                        continue
                    depth -= 1
                    if depth != 2:  # only direct children of <w:body>
                        continue
                    handle(el)
                    el.clear()
            except ET.ParseError as exc:
                raise HandlerError(f"malformed word/document.xml: {exc}") from exc
        flush()

        if "word/footnotes.xml" in zf.namelist():
            try:
                fr = ET.fromstring(guard_xml(zf.read("word/footnotes.xml")))
                notes = [
                    t
                    for fn in fr.findall(f"{W}footnote")
                    if fn.get(f"{W}type") in (None, "normal")
                    for t in [" ".join(_text(fn).split())]
                    if t
                ]
                if notes:
                    sections.append(Section(("Footnotes",), "\n".join(notes)))
            except ET.ParseError:
                doc.warnings.append("footnotes.xml unreadable")
        images = sum(1 for n in zf.namelist() if n.startswith("word/media/"))
        if images:
            doc.warnings.append(f"{images} embedded image(s) not indexed")
            doc.metadata["images"] = str(images)
        doc.sections = sections
        return doc
