"""
Tier-aware size policy (ADR-12).

The product runs from a laptop to a datacenter on the same code, so the *size behaviour* is
configuration, not code: how large a chunk may be, whether full paths are stored or derived
from the parent chain, and whether search should collapse curated duplicates.

Hard rule shared by every profile: NEVER truncate. Text longer than a chunk is split into
overlapping spans that together cover every character; nothing is dropped to fit a limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class SizePolicy:
    name: str
    chunk_chars: int  # target maximum characters per chunk
    chunk_overlap: int  # characters shared between consecutive chunks
    store_paths: bool  # persist path_text on topic_nodes (else derive via the topic_paths view)
    collapse_derived: bool  # search layer should collapse composite records under their native topic
    max_file_chars: Optional[int] = None  # above this a file is indexed as a flagged catalog card, not in full

    def __post_init__(self) -> None:
        if self.chunk_chars < 200:
            raise ValueError("chunk_chars must be >= 200")
        if not 0 <= self.chunk_overlap <= self.chunk_chars // 4:
            raise ValueError("chunk_overlap must be between 0 and chunk_chars // 4")


PROFILES: Dict[str, SizePolicy] = {
    # Tier 1: laptop, zero-copy. Smallest footprint: derive paths, collapse duplicates.
    "desktop": SizePolicy("desktop", chunk_chars=2000, chunk_overlap=150, store_paths=False, collapse_derived=True, max_file_chars=300_000),
    # Tier 2: edge appliance. Stores paths for fast joins, still collapses duplicates.
    "edge": SizePolicy("edge", chunk_chars=3000, chunk_overlap=200, store_paths=True, collapse_derived=True, max_file_chars=1_000_000),
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


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(hit: dict) -> set:
    text = hit.get("content") or hit.get("text") or hit.get("match_snippet") or ""
    return set(_TOKEN.findall(str(text)[:6000].lower()))


def _overlap(a: dict, b: dict) -> float:
    """Shared tokens relative to the LARGER text (1.0 = the same words). A record that contains the other
    plus extra information scores below 1.0, so it is never mistaken for a duplicate."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def collapse_by_topic(results: Sequence[dict], min_overlap: Optional[float] = None) -> List[dict]:
    """Search-time de-duplication of curated duplicates. `results` are ranked dicts carrying
    `topic_id` and `record_kind`.

    A `composite` record (a curated record standing on a native item) is folded into the native
    record of the same topic when that native is also in the results; the native keeps its rank
    and gets `collapsed` = number of composites folded into it. Natives are never folded together
    (different chunks of one section are different evidence), and records with no topic, or a
    composite whose native is not in the results, pass through untouched.

    `min_overlap` (0..1): when given, a composite is folded only if its text is at least that
    similar (shared tokens relative to the larger text) to the native's, so curated records that add information are kept.
    """
    first_native: Dict[object, int] = {}
    for i, r in enumerate(results):
        tid = r.get("topic_id")
        if tid and r.get("record_kind") == "native" and tid not in first_native:
            first_native[tid] = i

    def folds(r: dict) -> bool:
        tid = r.get("topic_id")
        if not (tid and r.get("record_kind") == "composite" and tid in first_native):
            return False
        return min_overlap is None or _overlap(r, results[first_native[tid]]) >= min_overlap

    out: List[dict] = []
    slot: Dict[int, dict] = {}
    for i, r in enumerate(results):
        if folds(r):
            continue
        item = dict(r)
        item["collapsed"] = 0
        out.append(item)
        slot[i] = item
    for r in results:
        if folds(r):
            slot[first_native[r["topic_id"]]]["collapsed"] += 1
    return out
