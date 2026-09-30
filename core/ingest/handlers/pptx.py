"""
PowerPoint (.pptx / .pptm) handler: one section per slide, in presentation order.

Slide title comes from the title placeholder (or the first text); shapes are read in reading
order including group shapes, tables become `cell | cell` rows, and speaker notes are appended
to their slide. Images and charts are counted, not indexed.
"""

from __future__ import annotations

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Dict, List

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register
from .xmlutil import guard_xml, local

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _paragraphs(el: ET.Element) -> List[str]:
    out: List[str] = []
    for p in el.iter(f"{A}p"):
        text = "".join(
            (t.text or "") if local(t.tag) == "t" else ("\n" if local(t.tag) == "br" else "")
            for t in p.iter()
            if local(t.tag) in ("t", "br")
        ).strip()
        if text:
            out.append(text)
    return out


def _rels(zf: zipfile.ZipFile, part: str) -> Dict[str, str]:
    rel = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rel not in zf.namelist():
        return {}
    base = posixpath.dirname(part)
    return {
        r.get("Id", ""): posixpath.normpath(posixpath.join(base, r.get("Target", "")))
        for r in ET.fromstring(guard_xml(zf.read(rel)))
    }


@register
class PptxHandler(FormatHandler):
    name = "pptx"
    version = "1"
    extensions = (".pptx", ".pptm", ".potx")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            pres = ET.fromstring(guard_xml(zf.read("ppt/presentation.xml")))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise HandlerError(f"not a readable .pptx: {exc}") from exc
        rels = _rels(zf, "ppt/presentation.xml")
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        images = 0
        for n, sid in enumerate(pres.iter(f"{P}sldId"), start=1):
            part = rels.get(sid.get(f"{R}id", ""))
            if not part or part not in zf.namelist():
                doc.warnings.append(f"slide {n}: part missing")
                continue
            try:
                slide = ET.fromstring(guard_xml(zf.read(part)))
            except ET.ParseError:
                doc.warnings.append(f"slide {n}: unreadable")
                continue
            title, lines = "", []
            for sp in slide.iter():
                tag = local(sp.tag)
                if tag == "sp":
                    ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                    paras = _paragraphs(sp)
                    if ph is not None and ph.get("type") in ("title", "ctrTitle") and paras and not title:
                        title = " ".join(paras)
                    else:
                        lines.extend(paras)
                elif tag == "tbl":
                    for tr in sp.iter(f"{A}tr"):
                        cells = [" ".join(_paragraphs(tc)) for tc in tr.findall(f"{A}tc")]
                        if any(cells):
                            lines.append(" | ".join(cells))
                elif tag == "pic":
                    images += 1
            notes = ""
            for rel_id, target in _rels(zf, part).items():
                if "notesSlide" in target and target in zf.namelist():
                    try:
                        nt = ET.fromstring(guard_xml(zf.read(target)))
                        body = [
                            t
                            for sp in nt.iter(f"{P}sp")
                            for ph in [sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")]
                            if ph is not None and ph.get("type") == "body"
                            for t in _paragraphs(sp)
                        ]
                        notes = "\n".join(body)
                    except ET.ParseError:
                        pass
            if not title and lines:
                title = lines.pop(0)
            text = "\n".join(lines)
            if notes:
                text = (text + "\n" if text else "") + "Speaker notes:\n" + notes
            if text.strip() or title:
                label = f"Slide {n}: {title}" if title else f"Slide {n}"
                doc.sections.append(Section((re.sub(r"\s+", " ", label)[:120],), text or title, locator=f"slide {n}"))
        if images:
            doc.warnings.append(f"{images} picture(s) not indexed")
        doc.metadata["slides"] = str(len(doc.sections))
        return doc
