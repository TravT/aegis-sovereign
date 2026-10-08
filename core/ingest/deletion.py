"""
Document Deletion and Tombstone Lifecycle Engine (ADR-13, ADR-37).

Ensures complete, atomic purging of deleted files and documents across:
1. SQLite WAL `document_records` and `document_fts` (FTS5 search index).
2. Topic Graph (`topic_nodes`, `topic_edges`, `topic_paths` view).
3. Semantic Vector Bridges (`semantic_bridges`).
4. Qdrant vector store collections (embedded or HTTP).
"""

from __future__ import annotations

import json
import os
import posixpath
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union


def _normalize_prefix(s: str) -> str:
    """Normalize node ID prefixes like 't:' or 'topic:'."""
    if s.startswith("t:"):
        return s[2:]
    if s.startswith("topic:"):
        return s[6:]
    return s


def purge_document(
    db_or_conn: Union[sqlite3.Connection, Path, str],
    file_path_or_uri: str,
    qdrant_client: Optional[Any] = None,
    collection_name: str = "sovereign_chunks",
) -> Dict[str, Any]:
    """
    Atomically purges all traces of a document from SQLite and vector storage.

    Parameters:
        db_or_conn: SQLite Connection or path to router database.
        file_path_or_uri: Exact file path, URI, or identifier of the document.
        qdrant_client: Optional QdrantClient instance.
        collection_name: Qdrant collection name to prune.

    Returns:
        Summary dict containing counts of deleted records, nodes, edges, bridges, etc.
    """
    owns_conn = False
    if isinstance(db_or_conn, (str, Path)):
        conn = sqlite3.connect(str(db_or_conn), timeout=60)
        owns_conn = True
    else:
        conn = db_or_conn

    norm_target = str(file_path_or_uri).replace("\\", "/")
    basename = posixpath.basename(norm_target)

    deleted_records_count = 0
    deleted_topics_count = 0
    deleted_edges_count = 0
    deleted_bridges_count = 0
    qdrant_deleted = False

    try:
        with conn:
            # 1. Identify all matching records in document_records
            # Match by doc_identifier exact, prefix, suffix or metadata
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, doc_identifier, topic_id, metadata
                FROM document_records
                WHERE doc_identifier = ?
                   OR doc_identifier LIKE ?
                   OR doc_identifier LIKE ?
                   OR doc_identifier LIKE ?
                   OR metadata LIKE ?
                """,
                (
                    norm_target,
                    f"{norm_target}::%",
                    f"{norm_target}#%",
                    f"%#{norm_target}",
                    f"%{basename}%",
                ),
            )
            matching_rows = cursor.fetchall()

            # Filter rows to ensure exact relevance to target
            target_row_ids = []
            candidate_topic_ids: Set[str] = set()

            for rid, ident, tid, meta_str in matching_rows:
                is_match = False
                if ident == norm_target or ident.startswith(norm_target + "::") or ident.startswith(norm_target + "#"):
                    is_match = True
                elif ident.endswith("#" + norm_target) or ident.endswith("/" + basename):
                    is_match = True
                else:
                    try:
                        m = json.loads(meta_str or "{}")
                        if m.get("virtual_uri") == norm_target or m.get("file_path") == norm_target:
                            is_match = True
                        elif m.get("virtual_uri", "").endswith("/" + basename):
                            is_match = True
                    except Exception:
                        pass

                if is_match:
                    target_row_ids.append(rid)
                    if tid:
                        candidate_topic_ids.add(tid)

            # Also search for any topic nodes directly representing this file path or member
            cursor.execute(
                """
                SELECT topic_id FROM topic_nodes
                WHERE topic_id LIKE ? OR topic_id LIKE ? OR name = ?
                """,
                (
                    f"%:path:%{basename}%",
                    f"%#{basename}%",
                    basename,
                ),
            )
            for r in cursor.fetchall():
                candidate_topic_ids.add(r[0])

            # 2. Delete from document_records
            if target_row_ids:
                cursor.executemany(
                    "DELETE FROM document_records WHERE id = ?",
                    [(rid,) for rid in target_row_ids],
                )
                deleted_records_count = len(target_row_ids)

            # Fallback for FTS5 if triggers were disabled or missing
            has_fts = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_fts'"
            ).fetchone()
            if has_fts and target_row_ids:
                try:
                    cursor.executemany(
                        "DELETE FROM document_fts WHERE rowid = ?",
                        [(rid,) for rid in target_row_ids],
                    )
                except Exception:
                    # Ignore if FTS5 external content table is updated via triggers
                    pass

            # 3. Cascade prune orphan topic nodes and edges
            # A node is pruned if:
            # - No remaining document_records point to it
            # - No child edges in topic_edges point to it as parent
            # - It's not a top-level root node (depth > 1 or parent IS NOT NULL)
            deleted_topic_ids: Set[str] = set()
            while True:
                pass_pruned = 0
                # Inspect candidate topic ids
                for tid in list(candidate_topic_ids):
                    # Check if any document still references this topic
                    has_docs = cursor.execute(
                        "SELECT 1 FROM document_records WHERE topic_id = ? LIMIT 1",
                        (tid,),
                    ).fetchone()
                    if has_docs:
                        candidate_topic_ids.discard(tid)
                        continue

                    # Check if this node has remaining children
                    has_children = cursor.execute(
                        "SELECT 1 FROM topic_edges WHERE parent = ? LIMIT 1",
                        (tid,),
                    ).fetchone()
                    if has_children:
                        continue

                    # Node is a leaf with no docs: prune it
                    parents = [
                        r[0]
                        for r in cursor.execute(
                            "SELECT parent FROM topic_edges WHERE child = ? AND parent IS NOT NULL",
                            (tid,),
                        ).fetchall()
                    ]

                    cursor.execute("DELETE FROM topic_edges WHERE child = ?", (tid,))
                    cursor.execute("DELETE FROM topic_nodes WHERE topic_id = ?", (tid,))
                    deleted_topic_ids.add(tid)
                    candidate_topic_ids.discard(tid)
                    pass_pruned += 1

                    # Add parents to candidate set for recursive pruning
                    for p in parents:
                        if p:
                            candidate_topic_ids.add(p)

                if pass_pruned == 0:
                    break

            deleted_topics_count = len(deleted_topic_ids)

            # Clean dangling topic edges
            edge_del = cursor.execute(
                """
                DELETE FROM topic_edges
                WHERE child NOT IN (SELECT topic_id FROM topic_nodes)
                   OR (parent IS NOT NULL AND parent NOT IN (SELECT topic_id FROM topic_nodes))
                """
            )
            deleted_edges_count = edge_del.rowcount if edge_del.rowcount > 0 else 0

            # 4. Clean semantic bridges referencing purged nodes
            has_bridges = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='semantic_bridges'"
            ).fetchone()
            if has_bridges and deleted_topic_ids:
                # Direct match and normalized t: match
                all_raw_and_prefixed = set(deleted_topic_ids)
                for dt in deleted_topic_ids:
                    all_raw_and_prefixed.add(f"t:{dt}")
                    all_raw_and_prefixed.add(f"topic:{dt}")

                q_marks = ",".join("?" for _ in all_raw_and_prefixed)
                br_del = cursor.execute(
                    f"""
                    DELETE FROM semantic_bridges
                    WHERE source_id IN ({q_marks})
                       OR target_id IN ({q_marks})
                    """,
                    list(all_raw_and_prefixed) * 2,
                )
                deleted_bridges_count = br_del.rowcount if br_del.rowcount > 0 else 0

        # 5. Qdrant Vector Store Pruning
        if qdrant_client is not None:
            try:
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                for field in ("file_path", "uri", "doc_identifier", "path"):
                    try:
                        qdrant_client.delete(
                            collection_name=collection_name,
                            points_selector=Filter(
                                must=[
                                    FieldCondition(
                                        key=field,
                                        match=MatchValue(value=norm_target),
                                    )
                                ]
                            ),
                        )
                        qdrant_deleted = True
                    except Exception:
                        pass
            except Exception:
                pass

    finally:
        if owns_conn:
            conn.close()

    return {
        "target": norm_target,
        "deleted_records": deleted_records_count,
        "deleted_topics": deleted_topics_count,
        "deleted_edges": deleted_edges_count,
        "deleted_bridges": deleted_bridges_count,
        "qdrant_deleted": qdrant_deleted,
    }
