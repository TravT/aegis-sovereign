"""
Shared, format-independent chunker.

Rules (the same for every file type and tier):
  * NEVER truncate: every character of every section ends up in at least one chunk; each chunk
    records the source spans it covers so this is provable (`coverage_gaps`).
  * small consecutive sections under the same parent heading are merged, so a manual with
    thousands of one-line sub-headings does not become thousands of records;
  * large sections are split with overlap at paragraph / line / word boundaries;
  * every chunk starts with a one-line context header `[document > heading > sub-heading]`,
    so it is self-explanatory in search results and in the full-text index.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from core.structure.policy import SizePolicy, chunk_spans

from .base import ParsedDocument, Section

_ROW_NO = re.compile(r"^(\d+): ", re.MULTILINE)
Span = Tuple[int, int, int]  # (section index, start, end) into that section's text


@dataclass(frozen=True)
class Chunk:
    index: int  # 0-based position in the document
    total: int
    path: Tuple[str, ...]  # heading path the chunk is filed under
    header: str
    body: str
    locator: str
    spans: Tuple[Span, ...]  # which source text this chunk covers

    @property
    def content(self) -> str:
        return f"{self.header}\n{self.body}"

    @property
    def suffix(self) -> str:
        return f"::part::{self.index + 1:04d}"


def _units(sections: Sequence[Section], policy: SizePolicy) -> List[List[int]]:
    """Group section indexes into chunking units: one big section, or a run of small siblings."""
    min_chars = max(policy.chunk_chars // 4, 200)
    units: List[List[int]] = []
    buf: List[int] = []
    buf_chars = 0

    def flush() -> None:
        nonlocal buf, buf_chars
        if buf:
            units.append(buf)
        buf, buf_chars = [], 0

    for i, s in enumerate(sections):
        big = len(s.text) >= min_chars or s.kind == "rows"
        if big:
            flush()
            units.append([i])
            continue
        if buf and sections[buf[0]].path[:-1] != s.path[:-1]:
            flush()
        buf.append(i)
        buf_chars += len(s.text)
        if buf_chars >= policy.chunk_chars:
            flush()
    flush()
    return units


def _unit_text(sections: Sequence[Section], unit: List[int]) -> Tuple[str, List[Tuple[int, int, int]]]:
    """Text of a unit plus [(section index, unit start, unit end)] so chunk spans map back to sources."""
    if len(unit) == 1:
        s = sections[unit[0]]
        return s.text, [(unit[0], 0, len(s.text))]
    parts: List[str] = []
    ranges: List[Tuple[int, int, int]] = []
    pos = 0
    for i in unit:
        s = sections[i]
        label = s.path[-1] if s.path else ""
        block = f"{label}\n" if label else ""
        start = pos + len(block)
        ranges.append((i, start, start + len(s.text)))
        parts.append(block + s.text)
        pos = start + len(s.text) + 2  # "\n\n" separator
    return "\n\n".join(parts), ranges


def chunk_document(doc: ParsedDocument, policy: SizePolicy) -> List[Chunk]:
    raw: List[Chunk] = []
    for unit in _units(doc.sections, policy):
        text, ranges = _unit_text(doc.sections, unit)
        if not text.strip():
            continue
        first = doc.sections[unit[0]]
        path = first.path if len(unit) == 1 else first.path[:-1]
        header = "[" + " > ".join((doc.title,) + tuple(path)) + "]"
        budget = max(policy.chunk_chars - len(header) - 1, 200)
        inner = dataclasses.replace(policy, chunk_chars=budget, chunk_overlap=min(policy.chunk_overlap, budget // 4))
        for a, b in chunk_spans(text, inner):
            spans = tuple(
                (si, max(a, u0) - u0, min(b, u1) - u0) for si, u0, u1 in ranges if max(a, u0) < min(b, u1)
            )
            locator = first.locator
            if len(unit) == 1 and first.kind == "rows":
                nums = _ROW_NO.findall(text[a:b])
                if nums:
                    locator = f"{first.locator} rows {nums[0]}-{nums[-1]}".strip()
            raw.append(Chunk(0, 0, tuple(path), header, text[a:b], locator, spans))
    total = len(raw)
    return [dataclasses.replace(c, index=i, total=total) for i, c in enumerate(raw)]


def coverage_gaps(doc: ParsedDocument, chunks: Sequence[Chunk]) -> List[Span]:
    """Source ranges that no chunk covers. Empty means the chunking was lossless."""
    covered = {i: [] for i in range(len(doc.sections))}
    for c in chunks:
        for si, a, b in c.spans:
            covered[si].append((a, b))
    gaps: List[Span] = []
    for si, s in enumerate(doc.sections):
        if not s.text.strip():
            continue
        pos = 0
        for a, b in sorted(covered[si]):
            if a > pos and s.text[pos:a].strip():
                gaps.append((si, pos, a))
            pos = max(pos, b)
        if pos < len(s.text) and s.text[pos:].strip():
            gaps.append((si, pos, len(s.text)))
    return gaps
