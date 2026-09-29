"""
Generic structure runner (ADR-12): apply any registered extractors to a router database.

Schema (additive, nullable, idempotent):
    topic_nodes(topic_id PK, package, name, depth, source, path_text NULL)
    topic_edges(child, parent NULL for roots, is_primary)   -- a topic with two parents keeps both
    topic_paths  VIEW  topic_id -> full " > " path, derived from the primary parent chain
    structure_meta(key, value)                              -- what was applied, with which policy
    document_records += topic_id, record_kind, console, plane
"""

from __future__ import annotations

import collections
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import Assignment, RecordView, StructureExtractor
from .policy import SizePolicy, get_profile
from .registry import extractor_for

TOPIC_PATHS_VIEW = """
CREATE VIEW topic_paths AS
WITH RECURSIVE up(tid, cur, path, d) AS (
    SELECT topic_id, topic_id, name, 0 FROM topic_nodes
    UNION ALL
    SELECT up.tid, e.parent, p.name || ' > ' || up.path, up.d + 1
    FROM up
    JOIN topic_edges e ON e.child = up.cur AND e.is_primary = 1
    JOIN topic_nodes p ON p.topic_id = e.parent
    WHERE up.d < 40
)
SELECT tid AS topic_id, path FROM up
WHERE NOT EXISTS (
    SELECT 1 FROM topic_edges e WHERE e.child = up.cur AND e.is_primary = 1 AND e.parent IS NOT NULL
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS topic_paths;
        DROP TABLE IF EXISTS topic_edges;
        DROP TABLE IF EXISTS topic_nodes;
        CREATE TABLE topic_nodes (
            topic_id TEXT PRIMARY KEY,
            package TEXT NOT NULL,
            name TEXT NOT NULL,
            depth INTEGER NOT NULL,
            source TEXT NOT NULL,
            path_text TEXT
        );
        CREATE TABLE topic_edges (
            child TEXT NOT NULL REFERENCES topic_nodes(topic_id),
            parent TEXT REFERENCES topic_nodes(topic_id),
            is_primary INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (child, parent)
        );
        CREATE INDEX idx_topic_edges_parent ON topic_edges(parent);
        CREATE TABLE IF NOT EXISTS structure_meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute(TOPIC_PATHS_VIEW)
    have = {r[1] for r in conn.execute("PRAGMA table_info(document_records)")}
    for col in ("topic_id", "record_kind", "console", "plane"):
        if col not in have:
            conn.execute(f"ALTER TABLE document_records ADD COLUMN {col} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_records_topic ON document_records(topic_id)")


def _virtual_uri(doc_identifier: str, metadata: Optional[str]) -> str:
    try:
        return json.loads(metadata or "{}").get("virtual_uri") or doc_identifier
    except (ValueError, TypeError, AttributeError):
        return doc_identifier


def build_extractors(sources: Dict[str, Path]) -> Dict[str, StructureExtractor]:
    """Detect and build one extractor per labelled source, in the order given."""
    out: Dict[str, StructureExtractor] = {}
    for label, path in sources.items():
        ex = extractor_for(Path(path), label)
        ex.build_tree()
        out[label] = ex
    return out


def apply_structure(
    db_path: Path,
    sources: Dict[str, Path],
    policy: Optional[SizePolicy] = None,
    dry_run: bool = False,
    extractors: Optional[Dict[str, StructureExtractor]] = None,
) -> Dict[str, object]:
    policy = policy or get_profile("edge")
    extractors = extractors if extractors is not None else build_extractors(sources)
    conn = sqlite3.connect(str(db_path), timeout=60)  # wait for a live service's write lock
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, doc_identifier, title, metadata FROM document_records").fetchall()

    upd: Dict[int, List[Optional[str]]] = {}  # id -> [topic_key, kind, console]
    stats: collections.Counter = collections.Counter()
    review: Dict[str, List[Dict[str, object]]] = collections.defaultdict(list)
    per_topic: Dict[str, List[int]] = collections.defaultdict(list)
    native_by_id: Dict[int, bool] = {}

    for r in rows:
        rec = RecordView(r["id"], r["doc_identifier"], r["title"], _virtual_uri(r["doc_identifier"], r["metadata"]))
        claimant = next((ex for ex in extractors.values() if ex.claims(rec)), None)
        if claimant is None:
            upd[rec.id] = [None, "external", None]
            stats["unclaimed:external"] += 1
            continue
        a: Assignment = claimant.assign(rec)
        stats[f"{claimant.name}:{a.kind}"] += 1
        if a.review:
            bucket = review[a.review.split(":")[0]]
            if len(bucket) < 25:
                bucket.append({"id": rec.id, "title": rec.title[:80], "why": a.review, "extractor": claimant.name})
        upd[rec.id] = [a.topic_key, a.kind, a.console]
        if a.topic_key:
            per_topic[a.topic_key].append(rec.id)
            native_by_id[rec.id] = a.kind == "native"

    # A topic keeps exactly one native record: promote the first record if none is native.
    for ids in per_topic.values():
        natives = [i for i in ids if native_by_id.get(i)]
        if not natives:
            upd[ids[0]][1] = "native"
            stats["promoted-to-native"] += 1
        elif len(natives) > 1:
            stats["topics-with-several-native"] += 1
    kinds = collections.Counter(u[1] for u in upd.values())

    report: Dict[str, object] = {
        "profile": policy.name,
        "records": len(rows),
        "extractors": {label: ex.name for label, ex in extractors.items()},
        "nodes": {label: len(ex.tree.nodes) for label, ex in extractors.items()},
        "edges": {label: len(ex.tree.edges) for label, ex in extractors.items()},
        "multi_parent_topics": {label: len(ex.tree.multi_parent) for label, ex in extractors.items()},
        "kinds": dict(kinds),
        "stats": dict(stats),
        "matched_topics": len(per_topic),
        "topics_with_several_records": sum(1 for v in per_topic.values() if len(v) > 1),
        "review": review,
        "dry_run": dry_run,
    }
    if dry_run:
        conn.close()
        return report

    with conn:
        ensure_schema(conn)
        conn.execute("UPDATE document_records SET topic_id=NULL, record_kind=NULL, console=NULL")
        for label, ex in extractors.items():
            conn.executemany(
                "INSERT INTO topic_nodes VALUES (?,?,?,?,?,?)",
                [
                    (n.key, label, n.name, n.depth, n.source, n.path_text if policy.store_paths else None)
                    for n in ex.tree.nodes.values()
                ],
            )
            conn.executemany("INSERT OR IGNORE INTO topic_edges VALUES (?,?,?)", ex.tree.edges)
        conn.executemany(
            "UPDATE document_records SET topic_id=?, record_kind=?, console=? WHERE id=?",
            [(u[0], u[1], u[2], i) for i, u in upd.items()],
        )
        meta = {
            "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "policy": json.dumps(policy.__dict__),
            "extractors": json.dumps(report["extractors"]),
            "kinds": json.dumps(report["kinds"]),
        }
        conn.executemany("INSERT OR REPLACE INTO structure_meta VALUES (?,?)", list(meta.items()))
    conn.close()
    for ex in extractors.values():
        ex.close()
    return report
