#!/usr/bin/env python3
"""
Sovereign Dual-Encoder Vector Indexer
FastEmbed int8 ONNX (Dense 384d) + Sparse BM25 RRF indexing.
Supports both remote Qdrant (HTTP) and embedded local path storage (Serverless).
"""

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    SparseVectorParams,
    PointStruct,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
)
from fastembed import TextEmbedding, SparseTextEmbedding

from core.chunker import parse_and_chunk_markdown, MarkdownChunk

DEFAULT_COLLECTION = os.getenv("SOVEREIGN_COLLECTION", "sovereign_chunks")
DEFAULT_DENSE_MODEL = os.getenv("SOVEREIGN_DENSE_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
DEFAULT_SPARSE_MODEL = os.getenv("SOVEREIGN_SPARSE_MODEL", "Qdrant/bm25")
DEFAULT_QDRANT_TARGET = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
DEFAULT_STATE_FILE = Path(os.getenv("SOVEREIGN_STATE_FILE", "data/rag/indexer_state.json"))


def compute_file_hash(filepath: Path) -> str:
    """Computes SHA-256 hex digest of a file's content."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_directory_hashes(target_dir: Path, extensions: Tuple[str, ...] = (".md", ".txt")) -> Dict[str, str]:
    """Scans all supported files in directory and maps relative path to SHA-256."""
    hashes = {}
    if not target_dir.exists():
        return hashes
    for ext in extensions:
        for p in target_dir.rglob(f"*{ext}"):
            if p.is_file():
                rel_path = str(p.relative_to(target_dir.parent if target_dir.is_absolute() else "."))
                hashes[rel_path] = compute_file_hash(p)
    return hashes


def calculate_state_diff(current_hashes: Dict[str, str], state: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    """Compares current file hashes with state index. Returns: (added_files, modified_files, deleted_files)"""
    added = []
    modified = []
    deleted = []

    for path, curr_hash in current_hashes.items():
        if path not in state:
            added.append(path)
        elif state[path].get("sha256") != curr_hash:
            modified.append(path)

    for path in state.keys():
        if path not in current_hashes:
            deleted.append(path)

    return added, modified, deleted


class SovereignIndexer:
    def __init__(
        self,
        qdrant_target: str = DEFAULT_QDRANT_TARGET,
        collection_name: str = DEFAULT_COLLECTION,
        dense_model_name: str = DEFAULT_DENSE_MODEL,
        sparse_model_name: str = DEFAULT_SPARSE_MODEL,
        client: Optional[QdrantClient] = None,
    ):
        self.qdrant_target = qdrant_target
        self.collection_name = collection_name
        self.dense_model_name = dense_model_name
        self.sparse_model_name = sparse_model_name

        # Support both HTTP URL and local path (for embedded serverless mode)
        if client is not None:
            self.client = client
        elif self.qdrant_target.startswith("http://") or self.qdrant_target.startswith("https://"):
            self.client = QdrantClient(url=self.qdrant_target)
        else:
            expanded_path = os.path.expanduser(self.qdrant_target)
            os.makedirs(expanded_path, exist_ok=True)
            self.client = QdrantClient(path=expanded_path)

        self._dense_model: Optional[TextEmbedding] = None
        self._sparse_model: Optional[SparseTextEmbedding] = None

    @property
    def dense_model(self) -> TextEmbedding:
        if self._dense_model is None:
            self._dense_model = TextEmbedding(model_name=self.dense_model_name)
        return self._dense_model

    @property
    def sparse_model(self) -> SparseTextEmbedding:
        if self._sparse_model is None:
            self._sparse_model = SparseTextEmbedding(model_name=self.sparse_model_name)
        return self._sparse_model

    def init_collection(self):
        """Ensures the Qdrant collection exists with dense and sparse vector configurations."""
        collections = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in collections:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    "dense": VectorParams(size=384, distance=Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams()
                }
            )
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="file_path",
                    field_schema="keyword"
                )
            except Exception:
                pass
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="clearance_level",
                    field_schema="integer"
                )
            except Exception:
                pass

    def delete_file_points(self, file_path: str):
        """Deletes all points in collection associated with a given file_path."""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="file_path",
                        match=MatchValue(value=file_path)
                    )
                ]
            )
        )

    def index_files(self, file_paths: List[str], base_dir: Path, default_clearance: Optional[int] = None) -> Dict[str, int]:
        """Chunks, embeds, and upserts points for each file in file_paths, storing clearance_level in payload."""
        result_counts = {}
        for rel_path in file_paths:
            full_path = Path(rel_path)
            if not full_path.is_absolute():
                candidates = [base_dir / rel_path, Path(rel_path)]
                for cand in candidates:
                    if cand.exists():
                        full_path = cand
                        break

            if not full_path.exists() or not full_path.is_file():
                continue

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue

            chunks = parse_and_chunk_markdown(content, str(full_path))
            if not chunks:
                continue

            texts = [c.text for c in chunks]
            dense_vectors = list(self.dense_model.embed(texts))
            sparse_vectors = list(self.sparse_model.embed(texts))

            points = []
            for i, chunk in enumerate(chunks):
                sp_vec = sparse_vectors[i]
                sparse_vector = SparseVector(
                    indices=sp_vec.indices.tolist(),
                    values=sp_vec.values.tolist()
                )

                chunk_clr = getattr(chunk, "clearance_level", 0)
                if default_clearance is not None and chunk_clr == 0:
                    chunk_clr = default_clearance

                payload = {
                    "doc_title": chunk.doc_title,
                    "file_path": str(full_path),
                    "heading": chunk.heading,
                    "tags": chunk.tags,
                    "aliases": chunk.aliases,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "clearance_level": chunk_clr,
                }

                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{full_path}#{chunk.chunk_index}"))
                points.append(
                    PointStruct(
                        id=point_id,
                        vector={
                            "dense": dense_vectors[i].tolist(),
                            "sparse": sparse_vector
                        },
                        payload=payload
                    )
                )

            self.delete_file_points(str(full_path))
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            result_counts[str(full_path)] = len(points)

        return result_counts
