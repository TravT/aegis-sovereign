"""
Tier-aware size policy (ADR-12).

The product runs from a laptop to a datacenter on the same code, so the *size behaviour* is
configuration, not code: how large a chunk may be, whether full paths are stored or derived
from the parent chain, and whether search should collapse curated duplicates.

Hard rule shared by every profile: NEVER truncate. Text longer than a chunk is split into
overlapping spans that together cover every character; nothing is dropped to fit a limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class SizePolicy:
    name: str
    chunk_chars: int  # target maximum characters per chunk
    chunk_overlap: int  # characters shared between consecutive chunks
    store_paths: bool  # persist path_text on topic_nodes (else derive via the topic_paths view)
    collapse_derived: bool  # search layer should collapse composite records under their native topic

    def __post_init__(self) -> None:
        if self.chunk_chars < 200:
            raise ValueError("chunk_chars must be >= 200")
        if not 0 <= self.chunk_overlap <= self.chunk_chars // 4:
            raise ValueError("chunk_overlap must be between 0 and chunk_chars // 4")


PROFILES: Dict[str, SizePolicy] = {
    # Tier 1: laptop, zero-copy. Smallest footprint: derive paths, collapse duplicates.
    "desktop": SizePolicy("desktop", chunk_chars=2000, chunk_overlap=150, store_paths=False, collapse_derived=True),
    # Tier 2: edge appliance. Stores paths for fast joins, still collapses duplicates.
    "edge": SizePolicy("edge", chunk_chars=3000, chunk_overlap=200, store_paths=True, collapse_derived=True),
    # Tier 3: datacenter. Larger chunks, keeps every derived record visible.
    "datacenter": SizePolicy("datacenter", chunk_chars=4000, chunk_overlap=300, store_paths=True, collapse_derived=False),
}


def get_profile(name: str) -> SizePolicy:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown size profile {name!r}; choose one of {sorted(PROFILES)}") from None


def chunk_spans(text: str, policy: SizePolicy) -> List[Tuple[int, int]]:
    """Overlapping [start, end) spans that cover every character of `text`, breaking at paragraph,
    line or word boundaries when one exists in the last 40% of a chunk."""
    n = len(text)
    if n == 0:
        return []
    if n <= policy.chunk_chars:
        return [(0, n)]
    spans: List[Tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + policy.chunk_chars, n)
        if end < n:
            lo = start + int(policy.chunk_chars * 0.6)
            cut = text.rfind("\n\n", lo, end)
            width = 2
            if cut == -1:
                cut, width = text.rfind("\n", lo, end), 1
            if cut == -1:
                cut, width = max(text.rfind(" ", lo, end), text.rfind("\t", lo, end)), 1
            if cut != -1:
                end = cut + width
        spans.append((start, end))
        if end >= n:
            return spans
        start = max(end - policy.chunk_overlap, spans[-1][0] + 1)


def chunk_text(text: str, policy: SizePolicy) -> List[str]:
    return [text[a:b] for a, b in chunk_spans(text, policy)]


def collapse_by_topic(results: Sequence[dict]) -> List[dict]:
    """Search-time de-duplication. `results` are ranked dicts carrying `topic_id` and `record_kind`.

    Keeps one result per topic, at the rank of its best-ranked member, preferring the native
    record when the topic has one. Records with no topic pass through untouched. Each kept
    result gets `collapsed` = number of other records folded into it.
    """
    order: List[object] = []
    best: Dict[object, dict] = {}
    folded: Dict[object, int] = {}
    for i, r in enumerate(results):
        tid = r.get("topic_id")
        key = tid if tid else ("_untopiced", i)
        if key not in best:
            best[key] = r
            folded[key] = 0
            order.append(key)
            continue
        folded[key] += 1
        if best[key].get("record_kind") != "native" and r.get("record_kind") == "native":
            best[key] = r
    out = []
    for key in order:
        item = dict(best[key])
        item["collapsed"] = folded[key]
        out.append(item)
    return out
