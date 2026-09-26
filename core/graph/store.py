#!/usr/bin/env python3
"""
Relational Knowledge Graph Store for Aegis Sovereign Knowledge Appliance.
Provides SQLite-backed persistence with WAL mode, foreign key constraints, graph indexing,
and relational traversal across documents, entities, and cross-document references.

Invariants:
- Zero Plaintext Secrets.
- Strictly local CPU execution using SQLite (WAL mode).
- Configurable via SOVEREIGN_GRAPH_DB_PATH.
"""

import os
import sqlite3
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Set, Tuple
from collections import deque

from .extractor import ExtractedEntity, ExtractedRelation

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_VAULT_GRAPH_DB = _REPO_ROOT / "docs" / ".aegis_vault" / "sovereign_graph.db"
DEFAULT_DB_PATH = Path(
    os.getenv(
        "SOVEREIGN_GRAPH_DB_PATH",
        str(_VAULT_GRAPH_DB) if _VAULT_GRAPH_DB.parent.exists() else "data/rag/graph_store.db",
    )
)

ALIAS_MAP: Dict[str, str] = {
    "irpf": "Declaração de Imposto de Renda",
    "dirpf": "Declaração de Imposto de Renda",
    "darf": "Documento de Arrecadação de Receitas Federais",
    "ha": "Home Assistant",
    "hass": "Home Assistant",
}


class GraphStore:
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            self.db_path = str(DEFAULT_DB_PATH)
        else:
            self.db_path = str(db_path)

        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")

        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def init_db(self) -> None:
        """Initializes relational schema, clearance columns, migrations, and indices."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Documents Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    corpus TEXT NOT NULL,
                    doc_identifier TEXT NOT NULL,
                    title TEXT,
                    created_date TEXT,
                    url TEXT,
                    clearance_level INTEGER DEFAULT 0,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(corpus, doc_identifier)
                );
            """)

            # 2. Entities Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    clearance_level INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(normalized_name, entity_type)
                );
            """)

            # 3. Document-Entity Junction Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS document_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    count INTEGER DEFAULT 1,
                    context TEXT,
                    UNIQUE(doc_id, entity_id)
                );
            """)

            # 4. Entity Relations Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL,
                    doc_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
                    clearance_level INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_entity_id, target_entity_id, relation_type, doc_id)
                );
            """)

            # Run migrations for existing databases
            cursor.execute("PRAGMA table_info(entities);")
            entity_cols = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in cursor.fetchall()]
            if "clearance_level" not in entity_cols:
                cursor.execute("ALTER TABLE entities ADD COLUMN clearance_level INTEGER DEFAULT 0;")

            cursor.execute("PRAGMA table_info(entity_relations);")
            rel_cols = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in cursor.fetchall()]
            if "clearance_level" not in rel_cols:
                cursor.execute("ALTER TABLE entity_relations ADD COLUMN clearance_level INTEGER DEFAULT 0;")

            cursor.execute("PRAGMA table_info(documents);")
            doc_cols = [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in cursor.fetchall()]
            if "clearance_level" not in doc_cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN clearance_level INTEGER DEFAULT 0;")

            # 5. Performance & Clearance Indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_normalized ON entities(normalized_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_clearance ON entities(clearance_level);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_entities_doc ON document_entities(doc_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_doc_entities_entity ON document_entities(entity_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON entity_relations(source_entity_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON entity_relations(target_entity_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_doc ON entity_relations(doc_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_clearance ON entity_relations(clearance_level);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_corpus_ident ON documents(corpus, doc_identifier);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_documents_clearance ON documents(clearance_level);")

            # Relations view for backward compatibility / convenience
            cursor.execute("CREATE VIEW IF NOT EXISTS relations AS SELECT * FROM entity_relations;")

            conn.commit()

    def _resolve_or_create_entity(
        self,
        cursor: sqlite3.Cursor,
        name: str,
        entity_type: Optional[str] = None,
        normalized_name: Optional[str] = None,
        clearance_level: int = 0
    ) -> int:
        norm = normalized_name if normalized_name else name.lower().strip()
        etype = entity_type if entity_type else "unknown"

        if entity_type:
            cursor.execute(
                "SELECT id, clearance_level FROM entities WHERE normalized_name = ? AND entity_type = ?",
                (norm, etype)
            )
            row = cursor.fetchone()
            if row:
                existing_clr = row["clearance_level"] if isinstance(row, sqlite3.Row) else row[1]
                if clearance_level > (existing_clr or 0):
                    cursor.execute("UPDATE entities SET clearance_level = ? WHERE id = ?", (clearance_level, row[0]))
                return row[0]

        cursor.execute("SELECT id, clearance_level FROM entities WHERE normalized_name = ?", (norm,))
        row = cursor.fetchone()
        if row:
            existing_clr = row["clearance_level"] if isinstance(row, sqlite3.Row) else row[1]
            if clearance_level > (existing_clr or 0):
                cursor.execute("UPDATE entities SET clearance_level = ? WHERE id = ?", (clearance_level, row[0]))
            return row[0]

        cursor.execute("SELECT id, clearance_level FROM entities WHERE name = ? COLLATE NOCASE", (name.strip(),))
        row = cursor.fetchone()
        if row:
            existing_clr = row["clearance_level"] if isinstance(row, sqlite3.Row) else row[1]
            if clearance_level > (existing_clr or 0):
                cursor.execute("UPDATE entities SET clearance_level = ? WHERE id = ?", (clearance_level, row[0]))
            return row[0]

        cursor.execute(
            """
            INSERT INTO entities (name, normalized_name, entity_type, clearance_level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(normalized_name, entity_type) DO UPDATE SET
                name = excluded.name,
                clearance_level = MAX(entities.clearance_level, excluded.clearance_level)
            RETURNING id;
            """,
            (name.strip(), norm, etype, int(clearance_level))
        )
        return cursor.fetchone()[0]

    def insert_entity(
        self,
        name: str,
        entity_type: str = "unknown",
        normalized_name: Optional[str] = None,
        clearance_level: int = 0
    ) -> int:
        """Inserts or updates an entity with a specific clearance level."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            eid = self._resolve_or_create_entity(
                cursor,
                name=name,
                entity_type=entity_type,
                normalized_name=normalized_name,
                clearance_level=clearance_level
            )
            conn.commit()
            return eid

    def insert_relation(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relation_type: str,
        doc_id: Optional[int] = None,
        clearance_level: int = 0
    ) -> int:
        """Inserts an entity relation with a specific clearance level."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO UPDATE SET
                    clearance_level = excluded.clearance_level
                RETURNING id;
                """,
                (source_entity_id, target_entity_id, relation_type, doc_id, int(clearance_level))
            )
            row = cursor.fetchone()
            rid = row[0] if row else 0
            conn.commit()
            return rid

    def index_document(
        self,
        corpus: str,
        doc_identifier: str,
        title: str,
        created_date: Optional[str] = None,
        url: Optional[str] = None,
        entities: Optional[List[Union[ExtractedEntity, Dict[str, Any]]]] = None,
        relations: Optional[List[Union[ExtractedRelation, Dict[str, Any]]]] = None,
        clearance_level: int = 0
    ) -> int:
        """Indexes or re-indexes a document and its extracted entities into the knowledge graph."""
        entities = entities or []
        relations = relations or []

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Upsert document
            cursor.execute(
                """
                INSERT INTO documents (corpus, doc_identifier, title, created_date, url, clearance_level, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(corpus, doc_identifier) DO UPDATE SET
                    title = excluded.title,
                    created_date = excluded.created_date,
                    url = excluded.url,
                    clearance_level = excluded.clearance_level,
                    indexed_at = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (corpus, doc_identifier, title, created_date, url, int(clearance_level))
            )
            doc_id = cursor.fetchone()[0]

            # 2. Clear old associations for idempotent re-indexing
            cursor.execute("DELETE FROM document_entities WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM entity_relations WHERE doc_id = ?", (doc_id,))

            # 3. Index Entities
            for e in entities:
                if isinstance(e, dict):
                    name = e.get("name", "")
                    etype = e.get("entity_type", "unknown")
                    norm = e.get("normalized_name", name.lower().strip())
                    ctx = e.get("context", "")
                    cnt = e.get("count", 1)
                    e_clearance = e.get("clearance_level", clearance_level)
                else:
                    name = e.name
                    etype = e.entity_type
                    norm = e.normalized_name if e.normalized_name else name.lower().strip()
                    ctx = e.context
                    cnt = e.count
                    e_clearance = getattr(e, "clearance_level", clearance_level)

                if not name or not norm:
                    continue

                eid = self._resolve_or_create_entity(
                    cursor,
                    name=name,
                    entity_type=etype,
                    normalized_name=norm,
                    clearance_level=e_clearance
                )

                cursor.execute(
                    """
                    INSERT INTO document_entities (doc_id, entity_id, count, context)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(doc_id, entity_id) DO UPDATE SET
                        count = excluded.count,
                        context = excluded.context;
                    """,
                    (doc_id, eid, cnt, ctx)
                )

            # 4. Index Relations
            for r in relations:
                if isinstance(r, dict):
                    src = r.get("source", "")
                    tgt = r.get("target", "")
                    rel_type = r.get("relation_type", "related_to")
                    src_type = r.get("source_type")
                    tgt_type = r.get("target_type")
                    r_clearance = r.get("clearance_level", clearance_level)
                else:
                    src = r.source
                    tgt = r.target
                    rel_type = r.relation_type
                    src_type = r.source_type
                    tgt_type = r.target_type
                    r_clearance = getattr(r, "clearance_level", clearance_level)

                if not src or not tgt or not rel_type:
                    continue

                src_id = self._resolve_or_create_entity(cursor, src, entity_type=src_type, clearance_level=r_clearance)
                tgt_id = self._resolve_or_create_entity(cursor, tgt, entity_type=tgt_type, clearance_level=r_clearance)

                cursor.execute(
                    """
                    INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO UPDATE SET
                        clearance_level = excluded.clearance_level;
                    """,
                    (src_id, tgt_id, rel_type, doc_id, int(r_clearance))
                )

            conn.commit()
            return doc_id

    def delete_document(self, corpus: str, doc_identifier: str) -> bool:
        """Deletes a document and cascades deletion of document_entities and entity_relations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM documents WHERE corpus = ? AND doc_identifier = ?", (corpus, doc_identifier))
            row = cursor.fetchone()
            if not row:
                return False
            doc_id = row[0]
            cursor.execute("DELETE FROM document_entities WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM entity_relations WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
            return True

    def delete_document_by_identifier(self, doc_identifier: str) -> int:
        """Deletes any document matching doc_identifier across all corpora."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM documents WHERE doc_identifier = ?", (doc_identifier,))
            rows = cursor.fetchall()
            if not rows:
                return 0
            count = 0
            for row in rows:
                doc_id = row[0]
                cursor.execute("DELETE FROM document_entities WHERE doc_id = ?", (doc_id,))
                cursor.execute("DELETE FROM entity_relations WHERE doc_id = ?", (doc_id,))
                cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
                count += 1
            conn.commit()
            return count

    def _find_entity(self, cursor: sqlite3.Cursor, query_name: str, max_clearance: int = 3) -> Optional[sqlite3.Row]:
        norm = query_name.lower().strip()
        alias = ALIAS_MAP.get(norm)
        alias_norm = alias.lower().strip() if alias else None

        if alias_norm:
            cursor.execute(
                """SELECT * FROM entities
                WHERE (normalized_name = ? OR name = ? COLLATE NOCASE)
                  AND clearance_level <= ?""",
                (alias_norm, alias, max_clearance)
            )
            row = cursor.fetchone()
            if row:
                return row

        cursor.execute(
            """SELECT * FROM entities
            WHERE (normalized_name = ? OR name = ? COLLATE NOCASE)
              AND clearance_level <= ?""",
            (norm, query_name.strip(), max_clearance)
        )
        row = cursor.fetchone()
        if row:
            return row

        # Fuzzy substring fallback
        cursor.execute(
            """
            SELECT e.*, COUNT(de.doc_id) as doc_count
            FROM entities e
            LEFT JOIN document_entities de ON e.id = de.entity_id
            WHERE (e.normalized_name LIKE ? OR e.name LIKE ?)
              AND e.clearance_level <= ?
            GROUP BY e.id
            ORDER BY doc_count DESC, length(e.name) ASC
            LIMIT 1;
            """,
            (f"%{norm}%", f"%{query_name.strip()}%", max_clearance)
        )
        row = cursor.fetchone()
        if row:
            return row

        # Compound query fallback: find the most specific entity whose name appears inside query_name
        cursor.execute(
            """
            SELECT e.*, COUNT(de.doc_id) as doc_count
            FROM entities e
            LEFT JOIN document_entities de ON e.id = de.entity_id
            WHERE length(e.normalized_name) >= 3
              AND ? LIKE '%' || e.normalized_name || '%'
              AND e.clearance_level <= ?
            GROUP BY e.id
            ORDER BY length(e.normalized_name) DESC, doc_count DESC
            LIMIT 1;
            """,
            (norm, max_clearance)
        )
        return cursor.fetchone()

    def get_entity_neighborhood(
        self,
        entity_name: str,
        max_depth: int = 1,
        max_clearance: int = 3
    ) -> Dict[str, Any]:
        """Traverses knowledge graph up to max_depth hops starting from entity_name, enforcing max_clearance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            root_row = self._find_entity(cursor, entity_name, max_clearance=max_clearance)
            if not root_row:
                return {
                    "entity": None,
                    "neighbors": [],
                    "documents": [],
                    "nodes": [],
                    "edges": []
                }

            root_dict = dict(root_row)
            root_id = root_dict["id"]

            visited_entities: Set[int] = {root_id}
            queue = deque([(root_id, 0)])
            neighbors: List[Dict[str, Any]] = []
            edges: List[Dict[str, Any]] = []
            nodes_map: Dict[int, Dict[str, Any]] = {root_id: root_dict}

            while queue:
                curr_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue

                cursor.execute(
                    """
                    SELECT r.target_entity_id as neighbor_id, r.relation_type, r.doc_id, r.clearance_level as rel_clearance, e.*
                    FROM entity_relations r
                    JOIN entities e ON r.target_entity_id = e.id
                    WHERE r.source_entity_id = ?
                      AND r.clearance_level <= ?
                      AND e.clearance_level <= ?
                    """,
                    (curr_id, max_clearance, max_clearance)
                )
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    nid = row_dict["neighbor_id"]
                    e_dict = {k: v for k, v in row_dict.items() if k not in ("neighbor_id", "relation_type", "doc_id", "rel_clearance")}
                    nodes_map[nid] = e_dict
                    edges.append({
                        "source": curr_id,
                        "target": nid,
                        "relation": row_dict["relation_type"],
                        "doc_id": row_dict["doc_id"],
                        "clearance_level": row_dict["rel_clearance"]
                    })
                    if nid not in visited_entities:
                        visited_entities.add(nid)
                        neighbors.append({
                            "entity": e_dict,
                            "relation": row_dict["relation_type"],
                            "direction": "outgoing",
                            "depth": depth + 1,
                            "doc_id": row_dict["doc_id"]
                        })
                        queue.append((nid, depth + 1))

                cursor.execute(
                    """
                    SELECT r.source_entity_id as neighbor_id, r.relation_type, r.doc_id, r.clearance_level as rel_clearance, e.*
                    FROM entity_relations r
                    JOIN entities e ON r.source_entity_id = e.id
                    WHERE r.target_entity_id = ?
                      AND r.clearance_level <= ?
                      AND e.clearance_level <= ?
                    """,
                    (curr_id, max_clearance, max_clearance)
                )
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    nid = row_dict["neighbor_id"]
                    e_dict = {k: v for k, v in row_dict.items() if k not in ("neighbor_id", "relation_type", "doc_id", "rel_clearance")}
                    nodes_map[nid] = e_dict
                    edges.append({
                        "source": nid,
                        "target": curr_id,
                        "relation": row_dict["relation_type"],
                        "doc_id": row_dict["doc_id"],
                        "clearance_level": row_dict["rel_clearance"]
                    })
                    if nid not in visited_entities:
                        visited_entities.add(nid)
                        neighbors.append({
                            "entity": e_dict,
                            "relation": row_dict["relation_type"],
                            "direction": "incoming",
                            "depth": depth + 1,
                            "doc_id": row_dict["doc_id"]
                        })
                        queue.append((nid, depth + 1))

            placeholders = ",".join("?" for _ in visited_entities)
            cursor.execute(
                f"""
                SELECT DISTINCT d.*
                FROM documents d
                JOIN document_entities de ON d.id = de.doc_id
                WHERE de.entity_id IN ({placeholders})
                  AND d.clearance_level <= ?
                ORDER BY d.created_date DESC;
                """,
                (*visited_entities, max_clearance)
            )
            documents = [dict(r) for r in cursor.fetchall()]

            return {
                "entity": root_dict,
                "neighbors": neighbors,
                "documents": documents,
                "nodes": list(nodes_map.values()),
                "edges": edges
            }

    def find_multi_hop_path(
        self,
        source_entity_name: str,
        target_entity_name: str,
        max_depth: int = 3,
        max_clearance: int = 3,
        max_hops: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Finds the shortest relational path between source and target entities,
        strictly pruning any nodes or edges where clearance_level > max_clearance.
        """
        if max_hops is not None:
            max_depth = max_hops
        with self._get_connection() as conn:
            cursor = conn.cursor()
            src_row = self._find_entity(cursor, source_entity_name, max_clearance=max_clearance)
            tgt_row = self._find_entity(cursor, target_entity_name, max_clearance=max_clearance)
            if not src_row or not tgt_row:
                return []

            src_id = src_row["id"]
            tgt_id = tgt_row["id"]
            if src_id == tgt_id:
                return []

            queue = deque([(src_id, [])])
            visited = {src_id}

            while queue:
                curr_id, path = queue.popleft()
                if len(path) >= max_depth:
                    continue

                cursor.execute(
                    """
                    SELECT r.id, r.target_entity_id as next_id, r.relation_type, r.clearance_level,
                           e_src.name as source_name, e_tgt.name as target_name
                    FROM entity_relations r
                    JOIN entities e_src ON r.source_entity_id = e_src.id
                    JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
                    WHERE r.source_entity_id = ?
                      AND r.clearance_level <= ?
                      AND e_tgt.clearance_level <= ?
                    """,
                    (curr_id, max_clearance, max_clearance)
                )
                for row in cursor.fetchall():
                    next_id = row["next_id"]
                    edge_info = {
                        "source_id": curr_id,
                        "source_name": row["source_name"],
                        "target_id": next_id,
                        "target_name": row["target_name"],
                        "relation": row["relation_type"],
                        "clearance_level": row["clearance_level"]
                    }
                    new_path = path + [edge_info]
                    if next_id == tgt_id:
                        return new_path
                    if next_id not in visited and len(new_path) < max_depth:
                        visited.add(next_id)
                        queue.append((next_id, new_path))

                cursor.execute(
                    """
                    SELECT r.id, r.source_entity_id as next_id, r.relation_type || ' (rev)' as relation_type, r.clearance_level,
                           e_tgt.name as source_name, e_src.name as target_name
                    FROM entity_relations r
                    JOIN entities e_src ON r.source_entity_id = e_src.id
                    JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
                    WHERE r.target_entity_id = ?
                      AND r.clearance_level <= ?
                      AND e_src.clearance_level <= ?
                    """,
                    (curr_id, max_clearance, max_clearance)
                )
                for row in cursor.fetchall():
                    next_id = row["next_id"]
                    edge_info = {
                        "source_id": curr_id,
                        "source_name": row["source_name"],
                        "target_id": next_id,
                        "target_name": row["target_name"],
                        "relation": row["relation_type"],
                        "clearance_level": row["clearance_level"]
                    }
                    new_path = path + [edge_info]
                    if next_id == tgt_id:
                        return new_path
                    if next_id not in visited and len(new_path) < max_depth:
                        visited.add(next_id)
                        queue.append((next_id, new_path))

            return []

    def query_relations(
        self,
        source_entity: Optional[str] = None,
        target_entity: Optional[str] = None,
        relation_type: Optional[str] = None,
        max_clearance: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Queries relations matching optional source, target, and relation_type,
        enforcing clearance_level <= max_clearance on relations and connected entities.
        """
        query = """
            SELECT r.id, r.relation_type, r.doc_id, r.clearance_level,
                   e_src.name as source_name, e_src.entity_type as source_type, e_src.clearance_level as source_clearance,
                   e_tgt.name as target_name, e_tgt.entity_type as target_type, e_tgt.clearance_level as target_clearance
            FROM entity_relations r
            JOIN entities e_src ON r.source_entity_id = e_src.id
            JOIN entities e_tgt ON r.target_entity_id = e_tgt.id
            WHERE r.clearance_level <= ?
              AND e_src.clearance_level <= ?
              AND e_tgt.clearance_level <= ?
        """
        params: List[Any] = [max_clearance, max_clearance, max_clearance]

        if source_entity:
            query += " AND (e_src.normalized_name = ? OR e_src.name = ? COLLATE NOCASE)"
            params.extend([source_entity.lower().strip(), source_entity.strip()])

        if target_entity:
            query += " AND (e_tgt.normalized_name = ? OR e_tgt.name = ? COLLATE NOCASE)"
            params.extend([target_entity.lower().strip(), target_entity.strip()])

        if relation_type:
            query += " AND r.relation_type = ?"
            params.append(relation_type)

        query += " ORDER BY r.id ASC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def compile_dossier(self, entity_name: str, max_clearance: int = 3) -> Dict[str, Any]:
        """Compiles a comprehensive dossier for an entity, enforcing max_clearance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            root_row = self._find_entity(cursor, entity_name, max_clearance=max_clearance)
            if not root_row:
                return {
                    "entity": None,
                    "total_documents": 0,
                    "documents": [],
                    "dates": [],
                    "amounts": [],
                    "total_monetary_amount": 0.0,
                    "connected_entities": {},
                    "relations": []
                }

            root_dict = dict(root_row)
            root_id = root_dict["id"]

            # Documents
            cursor.execute(
                """
                SELECT DISTINCT d.*
                FROM documents d
                JOIN document_entities de ON d.id = de.doc_id
                WHERE de.entity_id = ?
                  AND d.clearance_level <= ?
                ORDER BY d.created_date ASC;
                """,
                (root_id, max_clearance)
            )
            docs = [dict(r) for r in cursor.fetchall()]
            doc_ids = [d["id"] for d in docs]

            amounts: List[Dict[str, Any]] = []
            dates: List[Dict[str, Any]] = []
            connected_entities: Dict[str, List[Dict[str, Any]]] = {}

            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                cursor.execute(
                    f"""
                    SELECT DISTINCT e.*, de.context
                    FROM entities e
                    JOIN document_entities de ON e.id = de.entity_id
                    WHERE de.doc_id IN ({placeholders})
                      AND e.clearance_level <= ?
                    ORDER BY e.name;
                    """,
                    (*doc_ids, max_clearance)
                )
                seen_connected_ids = set()
                for row in cursor.fetchall():
                    e = dict(row)
                    etype = e["entity_type"]

                    if etype == "monetary":
                        amounts.append(e)
                    elif etype == "date":
                        dates.append(e)

                    if e["id"] != root_id and e["id"] not in seen_connected_ids:
                        seen_connected_ids.add(e["id"])
                        if etype not in ("monetary", "date"):
                            if etype not in connected_entities:
                                connected_entities[etype] = []
                            connected_entities[etype].append(e)

            # Deduplicate dates
            unique_dates: Dict[str, Dict[str, Any]] = {}
            for d in dates:
                norm_d = d.get("normalized_name") or d["name"]
                if norm_d not in unique_dates:
                    unique_dates[norm_d] = d
            dates = list(unique_dates.values())
            dates.sort(key=lambda x: x.get("normalized_name") or x["name"])

            # Deduplicate amounts
            unique_amounts: Dict[str, Dict[str, Any]] = {}
            total_amount = 0.0
            for a in amounts:
                raw_name = a["name"]
                clean_num = re.sub(r'[^\d,]', '', raw_name).replace(',', '.')
                try:
                    val = float(clean_num)
                except ValueError:
                    val = 0.0
                if val > 0 and raw_name not in unique_amounts:
                    a_copy = dict(a)
                    a_copy["parsed_value"] = val
                    unique_amounts[raw_name] = a_copy
                    total_amount += val

            # Direct relations
            cursor.execute(
                """
                SELECT r.relation_type, r.clearance_level, e.name as target_name, e.entity_type as target_type, 'outgoing' as direction
                FROM entity_relations r
                JOIN entities e ON r.target_entity_id = e.id
                WHERE r.source_entity_id = ?
                  AND r.clearance_level <= ?
                  AND e.clearance_level <= ?
                UNION
                SELECT r.relation_type, r.clearance_level, e.name as target_name, e.entity_type as target_type, 'incoming' as direction
                FROM entity_relations r
                JOIN entities e ON r.source_entity_id = e.id
                WHERE r.target_entity_id = ?
                  AND r.clearance_level <= ?
                  AND e.clearance_level <= ?
                """,
                (root_id, max_clearance, max_clearance, root_id, max_clearance, max_clearance)
            )
            relations = [dict(r) for r in cursor.fetchall()]

            return {
                "entity": root_dict,
                "total_documents": len(docs),
                "documents": docs,
                "dates": dates,
                "amounts": list(unique_amounts.values()),
                "total_monetary_amount": round(total_amount, 2),
                "connected_entities": connected_entities,
                "relations": relations
            }

    def get_entity_statistics(self) -> Dict[str, Any]:
        """Returns aggregate metrics on the knowledge graph."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM documents;")
            doc_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM entities;")
            entity_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM entity_relations;")
            relation_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT entity_type, COUNT(*) as cnt
                FROM entities
                GROUP BY entity_type
                ORDER BY cnt DESC;
            """)
            type_counts = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_documents": doc_count,
                "total_entities": entity_count,
                "total_relations": relation_count,
                "entities_by_type": type_counts,
                "db_path": self.db_path
            }

    def purge_documents_by_prefix(self, prefix: str) -> Dict[str, int]:
        """
        Deletes matching documents from `documents` (matching doc_identifier, url, or corpus prefix),
        deletes their associated edges from `entity_relations` (relations) and `document_entities`,
        and cleans up orphaned entities in `entities`.
        Returns {"deleted_graph_docs": doc_cnt, "deleted_relations": rel_cnt, "deleted_orphan_entities": ent_cnt}.
        """
        clean_prefix = (prefix or "").strip()
        if not clean_prefix:
            return {"deleted_graph_docs": 0, "deleted_relations": 0, "deleted_orphan_entities": 0}

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM documents
                WHERE doc_identifier LIKE ?
                   OR doc_identifier LIKE ?
                   OR COALESCE(url, '') LIKE ?
                   OR corpus = ?
                """,
                (f"{clean_prefix}%", f"%{clean_prefix}%", f"%{clean_prefix}%", clean_prefix),
            )
            doc_ids = [row[0] for row in cursor.fetchall()]

            rel_cnt = 0
            doc_cnt = 0
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                cursor.execute(
                    f"DELETE FROM entity_relations WHERE doc_id IN ({placeholders})",
                    doc_ids,
                )
                rel_cnt += cursor.rowcount
                cursor.execute(
                    f"DELETE FROM document_entities WHERE doc_id IN ({placeholders})",
                    doc_ids,
                )
                cursor.execute(
                    f"DELETE FROM documents WHERE id IN ({placeholders})",
                    doc_ids,
                )
                doc_cnt = cursor.rowcount

            # Clean up any orphaned entities no longer referenced by any relation or document
            cursor.execute(
                """
                DELETE FROM entities
                WHERE id NOT IN (
                    SELECT source_entity_id FROM entity_relations
                    UNION
                    SELECT target_entity_id FROM entity_relations
                    UNION
                    SELECT entity_id FROM document_entities
                )
                """
            )
            ent_cnt = cursor.rowcount
            conn.commit()

        return {
            "deleted_graph_docs": doc_cnt,
            "deleted_relations": rel_cnt,
            "deleted_orphan_entities": ent_cnt,
        }
