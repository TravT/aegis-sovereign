"""
HTML and XML handlers.

HTML: headings h1..h6 build the section tree; script / style / head content is ignored; table
rows become `cell | cell`; list items become `- item`.

XML: WSDL and XSD get purpose-built views (services and endpoints, operations with their
input / output / fault messages, message parts, and type definitions with their fields);
any other XML is linearised as `path/to/element [attr=value]: text` lines, one section per
top-level child of the root. Entity declarations are rejected.
"""

from __future__ import annotations

import html.parser
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register
from .text import decode_text
from .xmlutil import guard_xml, local

_SKIP = {"script", "style", "noscript", "head", "template"}
_BLOCK = {"p", "div", "br", "tr", "li", "section", "article", "table", "ul", "ol", "pre", "blockquote", "dd", "dt", "figcaption"}


class _Html(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections: List[Section] = []
        self._stack: List[Tuple[int, str]] = []
        self._lines: List[str] = []
        self._cur: List[str] = []
        self._cells: List[str] = []
        self._skip = 0
        self._in_title = False
        self._heading: Optional[int] = None
        self._htext: List[str] = []
        self._cell_depth = 0

    def _newline(self) -> None:
        text = " ".join("".join(self._cur).split())
        if text:
            self._lines.append(text)
        self._cur = []

    def _flush(self) -> None:
        self._newline()
        body = "\n".join(self._lines).strip("\n")
        if body.strip():
            self.sections.append(Section(tuple(t for _, t in self._stack), body))
        self._lines = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
            if tag == "head":
                return
        if tag == "title":
            self._in_title = True
        if self._skip:
            return
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            self._newline()
            self._heading, self._htext = int(tag[1]), []
        elif tag in ("td", "th"):
            self._cell_depth += 1
            self._cells.append("")
            self._cur_backup = self._cur
            self._cur = []
        elif tag == "li":
            self._newline()
            self._cur.append("- ")
        elif tag in _BLOCK:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(self._skip - 1, 0)
            return
        if tag == "title":
            self._in_title = False
        if self._skip:
            return
        if self._heading is not None and tag == f"h{self._heading}":
            text = " ".join("".join(self._htext).split())
            if text:
                self._flush()
                while self._stack and self._stack[-1][0] >= self._heading:
                    self._stack.pop()
                self._stack.append((self._heading, text))
            self._heading = None
        elif tag in ("td", "th") and self._cell_depth:
            self._cell_depth -= 1
            cell = " ".join("".join(self._cur).split())
            self._cur = self._cur_backup
            self._cells[-1] = cell
        elif tag == "tr":
            if any(self._cells):
                self._lines.append(" | ".join(self._cells))
            self._cells = []
        elif tag in _BLOCK:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._skip:
            return
        if self._heading is not None:
            self._htext.append(data)
        else:
            self._cur.append(data)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


@register
class HtmlHandler(FormatHandler):
    name = "html"
    version = "1"
    extensions = (".html", ".htm", ".xhtml")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        p = _Html()
        try:
            p.feed(decode_text(data))
            p.close()
        except Exception as exc:  # html.parser is lenient; anything else is a real failure
            raise HandlerError(f"unreadable HTML: {exc}") from exc
        doc = ParsedDocument(name=name, format=self.name, title=" ".join(p.title.split()) or self.title_from(name))
        doc.sections = p.sections
        return doc


# ---------------------------------------------------------------------------------------- XML
def _doc(el: ET.Element) -> str:
    d = next((c for c in el if local(c.tag) == "documentation"), None)
    if d is None:
        d = next((x for x in el.iter() if local(x.tag) == "documentation"), None)
    return " ".join("".join(d.itertext()).split()) if d is not None else ""


def _type_lines(root: ET.Element) -> List[str]:
    out: List[str] = []
    for el in root.iter():
        t = local(el.tag)
        if t in ("complexType", "simpleType", "element") and el.get("name") and (el in list(root) or t != "element" or True):
            fields = []
            for f in el.iter():
                ft = local(f.tag)
                if ft == "element" and f is not el and f.get("name"):
                    occ = f.get("maxOccurs")
                    fields.append(f"{f.get('name')}:{f.get('type', 'inline')}" + (f"[{occ}]" if occ and occ != "1" else ""))
                elif ft == "enumeration" and f.get("value"):
                    fields.append(f"={f.get('value')}")
                elif ft == "extension" and f.get("base"):
                    fields.append(f"extends {f.get('base')}")
            desc = f" {_doc(el)}" if _doc(el) else ""
            base = f" ({el.get('type')})" if el.get("type") else ""
            out.append(f"{t} {el.get('name')}{base}: " + ", ".join(fields) + desc)
    return out


@register
class XmlHandler(FormatHandler):
    name = "xml"
    version = "1"
    extensions = (".xml", ".wsdl", ".xsd", ".xsl", ".xslt", ".svg", ".rss", ".atom")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            root = ET.fromstring(guard_xml(data))
        except ET.ParseError as exc:
            raise HandlerError(f"malformed XML: {exc}") from exc
        kind = local(root.tag)
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        if kind == "definitions":
            self._wsdl(root, doc)
        elif kind == "schema":
            lines = _type_lines(root)
            if lines:
                doc.sections.append(Section(("Schema types",), "\n".join(lines)))
        else:
            self._generic(root, doc)
        doc.metadata["root"] = kind
        return doc

    @staticmethod
    def _wsdl(root: ET.Element, doc: ParsedDocument) -> None:
        doc.metadata["kind"] = "wsdl"
        svc: List[str] = []
        for s in (e for e in root.iter() if local(e.tag) == "service"):
            for port in (e for e in s if local(e.tag) == "port"):
                addr = next((a.get("location") for a in port.iter() if local(a.tag) == "address" and a.get("location")), "")
                svc.append(f"service {s.get('name')} port {port.get('name')} binding {port.get('binding')} {addr}".strip())
        if svc:
            doc.sections.append(Section(("Services",), "\n".join(svc)))
        ops: List[str] = []
        for pt in (e for e in root if local(e.tag) == "portType"):
            for op in (e for e in pt if local(e.tag) == "operation"):
                io_ = [f"{local(c.tag)}={c.get('message')}" for c in op if local(c.tag) in ("input", "output", "fault")]
                d = _doc(op)
                ops.append(f"{pt.get('name')}.{op.get('name')}: " + ", ".join(io_) + (f" — {d}" if d else ""))
        if ops:
            doc.sections.append(Section(("Operations",), "\n".join(ops)))
        msgs = [
            f"message {m.get('name')}: " + ", ".join(f"{p.get('name')}:{p.get('element') or p.get('type')}" for p in m if local(p.tag) == "part")
            for m in root
            if local(m.tag) == "message"
        ]
        if msgs:
            doc.sections.append(Section(("Messages",), "\n".join(msgs)))
        types = [t for e in root if local(e.tag) == "types" for s in e for t in _type_lines(s)]
        if types:
            doc.sections.append(Section(("Types",), "\n".join(types)))

    @staticmethod
    def _generic(root: ET.Element, doc: ParsedDocument) -> None:
        def lines(el: ET.Element, path: str) -> List[str]:
            here = f"{path}/{local(el.tag)}"
            attrs = " ".join(f"[{local(k)}={v}]" for k, v in el.attrib.items())
            text = " ".join((el.text or "").split())
            head = f"{here} {attrs}" if attrs else here
            out = ([f"{head}: {text}" if text else head]) if (text or attrs) else []
            for ch in el:
                out.extend(lines(ch, here))
            return out

        top = list(root)
        if not top:
            body = lines(root, "")
            if body:
                doc.sections.append(Section((local(root.tag),), "\n".join(body)))
            return
        head = lines(ET.Element(root.tag, root.attrib), "")
        if head:
            doc.sections.append(Section((local(root.tag),), "\n".join(head)))
        for i, ch in enumerate(top, start=1):
            body = lines(ch, "/" + local(root.tag))
            if body:
                doc.sections.append(Section((local(root.tag), f"{local(ch.tag)} #{i}"), "\n".join(body)))
