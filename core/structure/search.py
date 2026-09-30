"""
Search-time use of the structure layer (ADR-12): fold curated duplicates out of ranked results.

`fold_duplicates` annotates hits with their `topic_id` / `record_kind` (one read-only query by id)
and folds a curated `composite` record under the `native` record of the same topic when their text
is near-identical, so duplicate pages stop occupying result slots. Records that add information
(different text) are always kept. It degrades to a no-op on databases without the structure columns
(older vaults, in-memory test databases), and the tier is chosen by `AEGIS_SIZE_PROFILE`
(desktop | edge | datacenter; default edge). Nothing is deleted: this only shapes what one query returns.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional, Sequence, Tuple

from .policy import SizePolicy, collapse_by_topic, get_profile

MIN_OVERLAP = 0.85  # text similarity (vs the larger text) above which a composite counts as a duplicate of its native
_BATCH = 500


def active_policy() -> SizePolicy:
    try:
        return get_profile(os.environ.get("AEGIS_SIZE_PROFILE", "edge"))
    except ValueError:
        return get_profile("edge")


def _annotations(db_path: str, ids: Sequence[int]) -> Optional[Dict[int, Tuple[Optional[str], Optional[str]]]]:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(document_records)")}
        if not {"topic_id", "record_kind"} <= cols:
            return None
        out: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
        for i in range(0, len(ids), _BATCH):
            chunk = list(ids[i : i + _BATCH])
            marks = ",".join("?" * len(chunk))
            for rid, tid, kind in conn.execute(f"SELECT id, topic_id, record_kind FROM document_records WHERE id IN ({marks})", chunk):
                out[rid] = (tid, kind)
        return out
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def fold_duplicates(db_path: Optional[str], hits: List[dict], limit: int) -> List[dict]:
    """Return at most `limit` hits with near-identical composite duplicates folded under their native."""
    if not hits:
        return hits
    policy = active_policy()
    if not policy.collapse_derived or not db_path or db_path == ":memory:":
        return hits[:limit]
    ids = [h["id"] for h in hits if isinstance(h.get("id"), int)]
    ann = _annotations(db_path, ids) if ids else None
    if not ann:
        return hits[:limit]
    annotated = []
    for h in hits:
        tid, kind = ann.get(h.get("id"), (None, None)) if isinstance(h.get("id"), int) else (None, None)
        annotated.append(dict(h, topic_id=tid, record_kind=kind))
    return collapse_by_topic(annotated, min_overlap=MIN_OVERLAP)[:limit]
