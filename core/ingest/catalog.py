"""
Catalog card: the explicit, flagged alternative to silently truncating bulk tabular data.

Rule (ADR-13): *prose is always indexed in full*; only tabular rows are subject to a tier's cap
(`SizePolicy.max_file_chars`, counted over a file's row sections). When a file's rows exceed the
cap, its largest sheets are replaced, one at a time, by a small *card* until the remainder fits,
so small sheets stay complete. A card states what the sheet contains (size, row count, the column
legend and the first rows) and the file keeps its source path, so it stays findable by sheet and
column names and the original can be opened. Cards are flagged `fidelity=catalog` in the record
metadata and listed in the ingestion report; nothing is ever dropped silently.
"""

from __future__ import annotations

from typing import List, Tuple

from .base import ParsedDocument, Section

SAMPLE_LINES = 5
SAMPLE_WIDTH = 300


def _card(s: Section, cap: int) -> Section:
    lines = s.text.split("\n")
    legend = [ln for ln in lines[:12] if ln.startswith("Column ")]
    sample = [ln for ln in lines[:12] if not ln.startswith("Column ")][:SAMPLE_LINES]
    clip = lambda ln: ln if len(ln) <= SAMPLE_WIDTH else ln[: SAMPLE_WIDTH - 1] + "…"
    head = (
        f"Catalog card: this sheet has {len(s.text):,} characters in {len(lines):,} rows, above this tier's "
        f"limit for tabular data ({cap:,} characters per file), so only its description and first rows are indexed. "
        "Open the source file for the full data."
    )
    return Section(s.path, "\n".join([head] + [clip(x) for x in legend + sample]), locator=s.locator, kind="text")


def apply_cap(doc: ParsedDocument, cap: int) -> Tuple[ParsedDocument, List[str]]:
    """Return (document with over-cap sheets replaced by cards, names of the carded sheets)."""
    rows = sorted((i for i, s in enumerate(doc.sections) if s.kind == "rows"), key=lambda i: -len(doc.sections[i].text))
    total = sum(len(doc.sections[i].text) for i in rows)
    carded = set()
    for i in rows:
        if total <= cap:
            break
        carded.add(i)
        total -= len(doc.sections[i].text)
    if not carded:
        return doc, []
    out = ParsedDocument(name=doc.name, format=doc.format, title=doc.title, metadata=dict(doc.metadata), warnings=list(doc.warnings))
    names = [" > ".join(doc.sections[i].path) for i in sorted(carded)]
    out.sections = [_card(s, cap) if i in carded else s for i, s in enumerate(doc.sections)]
    out.metadata.update(fidelity="catalog", carded_sections="; ".join(names)[:500])
    out.warnings.append(f"{len(carded)} sheet(s) indexed as catalog cards (tabular data above {cap:,} chars per file): {', '.join(names)[:200]}")
    return out, names
