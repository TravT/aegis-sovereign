"""
Semantic Vector Bridge Engine for Aegis Sovereign Appliance
Supports three operational strategies aligned with commercial deployment tiers:
- Strategy A (Tier 1: Personal Desktop): Offline Pre-computed k-NN Bridges (SQLite Table)
- Strategy B (Tier 3: Enterprise Datacenter): Dynamic On-Demand Real-Time Vector Bridges (Live Query)
- Strategy C (Tier 2: Edge Turnkey 1U): Hybrid Tiered Bridges (Static Macro + Dynamic Micro)
"""

import math
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

TOPIC_PREFIX = "t:"
PACKAGE_PREFIX = "pkg:"


@dataclass
class SemanticBridge:
    source_id: str
    target_id: str
    similarity: float
    rationale: str
    source_name: str = ""
    target_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "similarity": round(self.similarity, 4),
            "rationale": self.rationale,
            "source_name": self.source_name,
            "target_name": self.target_name,
        }


class VectorSpaceEncoder:
    """
    Dual-mode vectorizer:
    1. Uses FastEmbed / EmbeddingGemma dense embeddings when available.
    2. Uses sublinear TF-IDF term vectorizer as ultra-fast zero-dependency fallback.
    """

    def __init__(self, use_dense: bool = False):
        self.use_dense = use_dense
        self._dense_model = None
        if self.use_dense:
            try:
                from fastembed import TextEmbedding
                self._dense_model = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            except Exception:
                self._dense_model = None
                self.use_dense = False

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        cleaned = re.sub(r"[^\w\s\-]", " ", text.lower())
        tokens = [t.strip("-") for t in cleaned.split() if len(t) > 2]
        stopwords = {
            "the", "and", "for", "with", "this", "that", "from", "into", "over",
            "under", "more", "most", "some", "such", "than", "then", "have", "has",
            "docx", "html", "htmls", "guide", "manual", "document", "documentation",
            "huawei", "virtual", "machine", "container"
        }
        return [t for t in tokens if t not in stopwords]

    def encode(self, text: str) -> Dict[str, float]:
        """Encodes text into a normalized sparse vector dictionary."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        counts = Counter(tokens)
        total = len(tokens)
        vec = {t: (1.0 + math.log(c)) / total for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            vec = {t: v / norm for t, v in vec.items()}
        return vec

    @staticmethod
    def cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
        """Computes cosine similarity between two normalized sparse vectors."""
        if not v1 or not v2:
            return 0.0
        # Dot product of normalized vectors
        if len(v1) > len(v2):
            v1, v2 = v2, v1
        return sum(val * v2.get(k, 0.0) for k, val in v1.items())


class SemanticBridgeEngine:
    """
    Unified Semantic Vector Bridge Engine powering:
    - Option A: Offline Pre-computed k-NN Bridges (SQLite Cached)
    - Option B: Dynamic Real-Time On-Demand Vector Bridges
    - Option C: Hybrid Tiered Bridges (Static Macro + Dynamic Micro)
    """

    def __init__(self, db_path: str, threshold: float = 0.65):
        self.db_path = db_path
        self.threshold = threshold
        self.encoder = VectorSpaceEncoder()
        self._ensure_schema()
        self._vector_cache: Dict[str, Dict[str, float]] = {}
        self._node_meta: Dict[str, Dict[str, Any]] = {}

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        """Ensures the semantic_bridges table exists in SQLite database."""
        if not self.db_path or self.db_path == ":memory:":
            return
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS semantic_bridges (
                        source_id TEXT,
                        target_id TEXT,
                        similarity REAL,
                        rationale TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (source_id, target_id)
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sem_bridge_source ON semantic_bridges(source_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sem_bridge_target ON semantic_bridges(target_id)")
        finally:
            conn.close()

    def _load_corpus_topics(self) -> List[Dict[str, Any]]:
        """Loads candidate topics and document texts from SQLite."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            query = """
                SELECT n.topic_id, n.package, n.name, n.depth, n.path_text,
                       d.title AS doc_title, SUBSTR(d.content, 1, 500) AS content_sample
                FROM topic_nodes n
                LEFT JOIN (
                    SELECT topic_id, title, content
                    FROM document_records
                    WHERE topic_id IS NOT NULL
                    GROUP BY topic_id
                ) d ON d.topic_id = n.topic_id
                WHERE n.depth <= 3
            """
            rows = cur.execute(query).fetchall()
            topics = []
            for r in rows:
                full_text = f"{r['name']} {r['path_text'] or ''} {r['doc_title'] or ''} {r['content_sample'] or ''}"
                topics.append({
                    "topic_id": r["topic_id"],
                    "package": r["package"],
                    "name": r["name"],
                    "depth": r["depth"],
                    "full_text": full_text
                })
            return topics
        finally:
            conn.close()

    def _get_or_compute_vector(self, topic: Dict[str, Any]) -> Dict[str, float]:
        tid = topic["topic_id"]
        if tid not in self._vector_cache:
            self._vector_cache[tid] = self.encoder.encode(topic["full_text"])
            self._node_meta[tid] = topic
        return self._vector_cache[tid]

    # =========================================================================
    # Strategy A: Offline Pre-computed k-NN Bridges (Tier 1: Desktop)
    # =========================================================================
    def compute_and_store_offline_bridges(self, k: int = 3, threshold: Optional[float] = None) -> int:
        """
        Runs an offline k-NN sweep across document/topic summary vectors and persists
        the top-k semantic bridges per node into the semantic_bridges SQLite table.
        """
        thresh = threshold or self.threshold
        topics = self._load_corpus_topics()
        if not topics:
            return 0

        # Group topics by companion packages
        by_companion: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for t in topics:
            pkg = t["package"]
            if pkg.startswith("REL_"):
                by_companion[pkg].append(t)
            else:
                by_companion[pkg].append(t)

        rel_packages = [p for p in by_companion if p.startswith("REL_")]
        bridges_to_insert = []

        for rel_pkg in rel_packages:
            target_pkg = "UPCF" if "UPCF" in rel_pkg else "USC"
            source_topics = by_companion[rel_pkg]
            target_topics = by_companion[target_pkg]

            for s_topic in source_topics:
                s_vec = self._get_or_compute_vector(s_topic)
                if not s_vec:
                    continue

                candidates: List[Tuple[float, Dict[str, Any], List[str]]] = []
                for t_topic in target_topics:
                    t_vec = self._get_or_compute_vector(t_topic)
                    sim = self.encoder.cosine_similarity(s_vec, t_vec)
                    if sim >= thresh:
                        shared = sorted(list(set(s_vec.keys()) & set(t_vec.keys())), key=lambda w: s_vec[w] * t_vec[w], reverse=True)[:3]
                        candidates.append((sim, t_topic, shared))

                candidates.sort(key=lambda x: x[0], reverse=True)
                for sim, t_top, shared in candidates[:k]:
                    rationale = f"Shared concept: {', '.join(shared)}" if shared else "Semantic alignment"
                    bridges_to_insert.append((
                        TOPIC_PREFIX + s_topic["topic_id"],
                        TOPIC_PREFIX + t_top["topic_id"],
                        sim,
                        rationale
                    ))

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("DELETE FROM semantic_bridges")
                conn.executemany("""
                    INSERT OR REPLACE INTO semantic_bridges (source_id, target_id, similarity, rationale)
                    VALUES (?, ?, ?, ?)
                """, bridges_to_insert)
            return len(bridges_to_insert)
        finally:
            conn.close()

    def get_offline_bridges(self, min_similarity: Optional[float] = None) -> List[SemanticBridge]:
        """Loads pre-computed semantic bridges from SQLite with sub-millisecond latency."""
        min_sim = min_similarity or self.threshold
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT b.source_id, b.target_id, b.similarity, b.rationale,
                       s.name AS source_name, t.name AS target_name
                FROM semantic_bridges b
                LEFT JOIN topic_nodes s ON s.topic_id = REPLACE(REPLACE(b.source_id, 'topic:', ''), 't:', '')
                LEFT JOIN topic_nodes t ON t.topic_id = REPLACE(REPLACE(b.target_id, 'topic:', ''), 't:', '')
                WHERE b.similarity >= ?
                ORDER BY b.similarity DESC
            """, (min_sim,)).fetchall()

            return [
                SemanticBridge(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    similarity=float(r["similarity"]),
                    rationale=r["rationale"] or "",
                    source_name=r["source_name"] or "",
                    target_name=r["target_name"] or ""
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_offline_bridges_for_node(self, source_id: str, k: int = 5) -> List[SemanticBridge]:
        """Loads pre-computed semantic bridges for a single node in sub-millisecond time."""
        raw_tid = source_id.replace("topic:", "").replace("t:", "")
        t_id = f"t:{raw_tid}"
        topic_id = f"topic:{raw_tid}"

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT b.source_id, b.target_id, b.similarity, b.rationale,
                       s.name AS source_name, t.name AS target_name
                FROM semantic_bridges b
                LEFT JOIN topic_nodes s ON s.topic_id = REPLACE(REPLACE(b.source_id, 'topic:', ''), 't:', '')
                LEFT JOIN topic_nodes t ON t.topic_id = REPLACE(REPLACE(b.target_id, 'topic:', ''), 't:', '')
                WHERE b.source_id = ? OR b.source_id = ?
                ORDER BY b.similarity DESC
                LIMIT ?
            """, (t_id, topic_id, k)).fetchall()

            return [
                SemanticBridge(
                    source_id=r["source_id"],
                    target_id=r["target_id"],
                    similarity=float(r["similarity"]),
                    rationale=r["rationale"] or "",
                    source_name=r["source_name"] or "",
                    target_name=r["target_name"] or ""
                )
                for r in rows
            ]
        finally:
            conn.close()

    # =========================================================================
    # Strategy B: Dynamic Real-Time On-Demand Vector Bridges (Tier 3: Datacenter)
    # =========================================================================
    def query_realtime_knn_bridges(self, source_id: str, k: int = 5, threshold: Optional[float] = None) -> List[SemanticBridge]:
        """
        Dynamically computes semantic bridges on demand for a given target node
        without reading from pre-computed database tables. Always fresh for live data.
        """
        thresh = threshold or self.threshold
        if source_id.startswith("topic:"):
            raw_tid = source_id[len("topic:"):]
        elif source_id.startswith("t:"):
            raw_tid = source_id[len("t:"):]
        else:
            raw_tid = source_id

        norm_source_id = f"t:{raw_tid}"

        # Fetch source topic
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            source_row = cur.execute("""
                SELECT n.topic_id, n.package, n.name, n.depth, n.path_text,
                       d.title AS doc_title, SUBSTR(d.content, 1, 500) AS content_sample
                FROM topic_nodes n
                LEFT JOIN (
                    SELECT topic_id, title, content
                    FROM document_records
                    WHERE topic_id IS NOT NULL
                    GROUP BY topic_id
                ) d ON d.topic_id = n.topic_id
                WHERE n.topic_id = ?
            """, (raw_tid,)).fetchone()

            if not source_row:
                return []

            source_pkg = source_row["package"]
            target_pkg = "UPCF" if "UPCF" in source_pkg else ("USC" if "USC" in source_pkg else None)
            if not target_pkg:
                target_pkg = "REL_UPCF" if source_pkg == "UPCF" else "REL_USC"

            source_text = f"{source_row['name']} {source_row['path_text'] or ''} {source_row['doc_title'] or ''} {source_row['content_sample'] or ''}"
            source_vec = self.encoder.encode(source_text)
            if not source_vec:
                return []

            # Inverted word filter: only inspect candidate topics sharing at least one token
            source_words = set(source_vec.keys())
            if not source_words:
                return []

            # Use word-boundary LIKE or token match to pre-filter candidates in SQL
            word_clauses = " OR ".join(["n.name LIKE ?"] * min(len(source_words), 5))
            top_words = sorted(list(source_words), key=lambda w: source_vec[w], reverse=True)[:5]
            word_params = [f"%{w}%" for w in top_words]

            query = f"""
                SELECT n.topic_id, n.package, n.name, n.depth, n.path_text,
                       d.title AS doc_title, SUBSTR(d.content, 1, 500) AS content_sample
                FROM topic_nodes n
                LEFT JOIN (
                    SELECT topic_id, title, content
                    FROM document_records
                    WHERE topic_id IS NOT NULL
                    GROUP BY topic_id
                ) d ON d.topic_id = n.topic_id
                WHERE n.package = ? AND n.depth <= 3 AND ({word_clauses})
            """
            target_rows = cur.execute(query, [target_pkg] + word_params).fetchall()

            candidates: List[SemanticBridge] = []
            for tr in target_rows:
                tid = tr["topic_id"]
                if tid in self._vector_cache:
                    target_vec = self._vector_cache[tid]
                else:
                    target_text = f"{tr['name']} {tr['path_text'] or ''} {tr['doc_title'] or ''} {tr['content_sample'] or ''}"
                    target_vec = self.encoder.encode(target_text)
                    self._vector_cache[tid] = target_vec

                sim = self.encoder.cosine_similarity(source_vec, target_vec)
                if sim >= thresh:
                    shared = sorted(list(set(source_vec.keys()) & set(target_vec.keys())), key=lambda w: source_vec[w] * target_vec[w], reverse=True)[:3]
                    rationale = f"Shared concept: {', '.join(shared)}" if shared else "Semantic alignment"
                    candidates.append(SemanticBridge(
                        source_id=norm_source_id,
                        target_id=TOPIC_PREFIX + tr["topic_id"],
                        similarity=sim,
                        rationale=rationale,
                        source_name=source_row["name"],
                        target_name=tr["name"]
                    ))

            candidates.sort(key=lambda b: b.similarity, reverse=True)
            return candidates[:k]
        finally:
            conn.close()

    # =========================================================================
    # Strategy C: Hybrid Tiered Bridges (Tier 2: Edge 1U)
    # =========================================================================
    def query_hybrid_bridges(self, source_id: str, k: int = 5) -> List[SemanticBridge]:
        """
        Combines Strategy A (pre-computed macro bridges for instant initial render)
        with Strategy B (dynamic real-time expansion when focusing on a specific node).
        """
        if source_id.startswith("topic:"):
            raw_tid = source_id[len("topic:"):]
        elif source_id.startswith("t:"):
            raw_tid = source_id[len("t:"):]
        else:
            raw_tid = source_id
        t_id = f"t:{raw_tid}"
        topic_id = f"topic:{raw_tid}"

        # 1. First attempt to fetch from pre-computed cache
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT b.source_id, b.target_id, b.similarity, b.rationale,
                       s.name AS source_name, t.name AS target_name
                FROM semantic_bridges b
                LEFT JOIN topic_nodes s ON s.topic_id = REPLACE(REPLACE(b.source_id, 'topic:', ''), 't:', '')
                LEFT JOIN topic_nodes t ON t.topic_id = REPLACE(REPLACE(b.target_id, 'topic:', ''), 't:', '')
                WHERE b.source_id = ? OR b.source_id = ?
                ORDER BY b.similarity DESC
                LIMIT ?
            """, (t_id, topic_id, k)).fetchall()

            if rows:
                return [
                    SemanticBridge(
                        source_id=r["source_id"],
                        target_id=r["target_id"],
                        similarity=float(r["similarity"]),
                        rationale=r["rationale"] or "",
                        source_name=r["source_name"] or "",
                        target_name=r["target_name"] or ""
                    )
                    for r in rows
                ]
        finally:
            conn.close()

        # 2. If not found in pre-computed macro table, dynamically query on demand
        return self.query_realtime_knn_bridges(source_id, k=k)
