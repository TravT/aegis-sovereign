"""
Plain text, Markdown and CSV / TSV handlers.

  * Markdown: ATX headings (`#`..`######`) build the section tree; fenced code blocks are text.
  * Plain text / logs / config files: one section (the chunker splits at paragraph and line
    boundaries). Anything with NUL bytes is refused as binary.
  * CSV / TSV: delimiter sniffed, then the same grid logic as spreadsheets (header + rows).
Encoding: UTF-8 (with or without BOM), UTF-16 with BOM, else Windows-1252 / Latin-1.
"""

from __future__ import annotations

import csv
import io
import re
from typing import List, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register
from .tables import grid_to_section

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def decode_text(data: bytes) -> str:
    if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise HandlerError("binary content (NUL bytes)")
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


@register
class MarkdownHandler(FormatHandler):
    name = "markdown"
    version = "1"
    extensions = (".md", ".markdown")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        text = decode_text(data)
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        stack: List[Tuple[int, str]] = []
        lines: List[str] = []
        fence = False

        def flush() -> None:
            body = "\n".join(lines).strip("\n")
            if body.strip():
                doc.sections.append(Section(tuple(t for _, t in stack), body))
            lines.clear()

        if text.startswith("---\n"):  # YAML front matter stays with the first section
            end = text.find("\n---", 4)
            if end != -1:
                lines.append(text[: end + 4])
                text = text[end + 4 :]
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                fence = not fence
            m = None if fence else _ATX.match(line)
            if m:
                flush()
                lvl = len(m.group(1))
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                stack.append((lvl, m.group(2).strip()))
            else:
                lines.append(line)
        flush()
        return doc


@register
class TextHandler(FormatHandler):
    name = "text"
    version = "1"
    extensions = (".txt", ".log", ".rst", ".ini", ".cfg", ".conf", ".yaml", ".yml", ".json", ".toml", ".properties")
    priority = 900  # generic

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        text = decode_text(data)
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        if text.strip():
            doc.sections.append(Section((), text.strip("\n")))
        return doc


@register
class CsvHandler(FormatHandler):
    name = "csv"
    version = "1"
    extensions = (".csv", ".tsv")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        text = decode_text(data)
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if name.lower().endswith(".tsv") else csv.excel
        cells = {}
        try:
            for r, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
                for c, v in enumerate(row, start=1):
                    if v.strip():
                        cells[(r, c)] = v
        except csv.Error as exc:
            raise HandlerError(f"malformed CSV: {exc}") from exc
        section = grid_to_section(doc.title, cells, [])
        if section is not None:
            doc.sections.append(section)
        return doc
