#!/usr/bin/env python3
"""
Embeds the native vendor manuals into Qdrant collection 'sovereign_chunks' (Finding O1).
Applies 768-d EmbeddingGemma ONNX dense vectors + BM25 sparse vectors.
Embeds ONLY native records (record_kind='native'), skipping composite duplicates.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository roots are in sys.path
APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
HUB_ROOT = APPLIANCE_ROOT.parent.parent
for p in [str(APPLIANCE_ROOT), str(HUB_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PayloadSchemaType,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from fastembed import SparseTextEmbedding
from scripts.embedding_gemma_onnx import EmbeddingGemmaONNX

DEFAULT_DB = HUB_ROOT / "docs" / ".aegis_vault" / "sovereign_router.db"
DEFAULT_COLLECTION = "sovereign_chunks"
DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")


def ensure_collection(client: QdrantClient, collection_name: str = DEFAULT_COLLECTION) -> None:
    """Creates the sovereign_chunks collection if it does not already exist."""
    collections = {c.name for c in client.get_collections().collections}
    if collection_name not in collections:
        print(f"Creating Qdrant collection '{collection_name}' (768-d Cosine + BM25 sparse)...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": VectorParams(size=768, distance=Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams()
            },
        )
        # Create payload indexes for fast MAC filtering and ID lookups
        client.create_payload_index(
            collection_name=collection_name,
            field_name="clearance_level",
            field_schema=PayloadSchemaType.INTEGER,
        )
        client.create_payload_index(
            collection_name=collection_name,
            field_name="doc_identifier",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=collection_name,
            field_name="topic_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print(f"Collection '{collection_name}' created successfully with payload indexes.")
    else:
        info = client.get_collection(collection_name)
        cnt = info.points_count
        print(f"Collection '{collection_name}' already exists with {cnt} points.")


def get_indexed_ids(client: QdrantClient, collection_name: str) -> set[int]:
    """Retrieves all integer IDs currently indexed in Qdrant for resume support."""
    indexed = set()
    offset = None
    while True:
        res = client.scroll(
            collection_name=collection_name,
            limit=1024,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        points, next_offset = res
        for p in points:
            if isinstance(p.id, int):
                indexed.add(p.id)
            elif isinstance(p.id, str) and p.id.isdigit():
                indexed.add(int(p.id))
        if next_offset is None or not points:
            break
        offset = next_offset
    return indexed


def index_manuals(
    db_path: Path = DEFAULT_DB,
    qdrant_url: str = DEFAULT_QDRANT_URL,
    collection_name: str = DEFAULT_COLLECTION,
    batch_size: int = 32,
    max_length: int = 512,
    limit: Optional[int] = None,
    benchmark_only: bool = False,
    threads: int = 2,
) -> Dict[str, Any]:
    client = QdrantClient(url=qdrant_url)
    ensure_collection(client, collection_name)

    print(f"Connecting to SQLite router database: {db_path}...")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Query only native records
    query = """
        SELECT id, doc_identifier, title, content, clearance_level, metadata, topic_id
        FROM document_records
        WHERE record_kind = 'native'
        ORDER BY id ASC
    """
    if limit is not None:
        query += f" LIMIT {limit}"

    rows = cur.execute(query).fetchall()
    total_rows = len(rows)
    print(f"Retrieved {total_rows} native records from SQLite.")

    # Check already indexed IDs if resuming
    already_indexed = get_indexed_ids(client, collection_name) if not benchmark_only else set()
    rows_to_index = [r for r in rows if r["id"] not in already_indexed]
    print(f"Found {len(rows_to_index)} records needing indexing ({len(already_indexed)} already in Qdrant).")

    if not rows_to_index:
        print("All matching native records are already indexed in Qdrant!")
        return {"total": total_rows, "indexed": 0, "already_indexed": len(already_indexed)}

    # Initialize Embedding Engines
    print(f"Loading EmbeddingGemmaONNX (768-d, threads={threads}, max_length={max_length})...")
    gemma = EmbeddingGemmaONNX(num_threads=threads, mrl_dim=768)
    print("Loading SparseTextEmbedding (BM25)...")
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

    start_time = time.time()
    processed = 0

    for i in range(0, len(rows_to_index), batch_size):
        batch_rows = rows_to_index[i : i + batch_size]
        batch_t0 = time.time()

        # Prepare document items for Gemma dense embedding: (title, text)
        doc_items = [(r["title"] or "", (r["content"] or "")[:1500]) for r in batch_rows]
        dense_vecs = gemma.encode_documents(doc_items, max_length=max_length)

        # Prepare text for BM25 sparse embedding
        sparse_texts = [f"{r['title'] or ''}\n{(r['content'] or '')[:2000]}" for r in batch_rows]
        sparse_res = list(sparse_model.embed(sparse_texts))

        # Build Qdrant PointStruct objects
        points = []
        for r, d_vec, sp_emb in zip(batch_rows, dense_vecs, sparse_res):
            meta_json = {}
            if r["metadata"]:
                try:
                    meta_json = json.loads(r["metadata"])
                except Exception:
                    pass

            v_uri = meta_json.get("virtual_uri", r["doc_identifier"])
            payload = {
                "doc_identifier": r["doc_identifier"],
                "title": r["title"] or "",
                "content": (r["content"] or "")[:3000],
                "clearance_level": int(r["clearance_level"] or 0),
                "topic_id": r["topic_id"] or "",
                "virtual_uri": v_uri,
                "record_kind": "native",
            }
            sp_vec = SparseVector(
                indices=sp_emb.indices.tolist(),
                values=sp_emb.values.tolist(),
            )
            points.append(
                PointStruct(
                    id=r["id"],
                    vector={
                        "dense": d_vec,
                        "sparse": sp_vec,
                    },
                    payload=payload,
                )
            )

        # Upsert batch to Qdrant
        client.upsert(collection_name=collection_name, points=points)
        processed += len(points)
        batch_elapsed = time.time() - batch_t0
        total_elapsed = time.time() - start_time
        rate = processed / total_elapsed
        ms_per_doc = (total_elapsed / processed) * 1000

        remaining = len(rows_to_index) - processed
        eta_sec = remaining / rate if rate > 0 else 0
        eta_min = eta_sec / 60

        print(
            f"[{processed}/{len(rows_to_index)}] Batch in {batch_elapsed:.2f}s | "
            f"Rate: {rate:.1f} rec/s ({ms_per_doc:.1f} ms/rec) | "
            f"ETA: {eta_min:.1f} min"
        )

    con.close()
    total_elapsed = time.time() - start_time
    print(f"\nCompleted {processed} records in {total_elapsed:.1f}s ({processed / total_elapsed:.1f} rec/s).")
    return {
        "processed": processed,
        "elapsed_seconds": total_elapsed,
        "rate": processed / total_elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to sovereign_router.db")
    parser.add_argument("--qdrant-url", type=str, default=DEFAULT_QDRANT_URL, help="Qdrant HTTP URL")
    parser.add_argument("--collection", type=str, default=DEFAULT_COLLECTION, help="Target collection")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size (default: 32)")
    parser.add_argument("--max-length", type=int, default=512, help="Max sequence length for ONNX dense embedding (default: 512)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of records to embed")
    parser.add_argument("--benchmark", action="store_true", help="Run 1,000-record benchmark and report estimate")
    parser.add_argument("--threads", type=int, default=2, help="ONNXRuntime threads (default: 2)")
    args = parser.parse_args()
    from tools.bounded_run import require
    require("manual indexing")  # step 12.6: capped, not 03:30-05:30

    if args.benchmark:
        limit = args.limit or 1000
        print(f"=== Running {limit}-Record Manuals Embedding Benchmark ===")
        res = index_manuals(
            db_path=args.db,
            qdrant_url=args.qdrant_url,
            collection_name=args.collection,
            batch_size=args.batch_size,
            max_length=args.max_length,
            limit=limit,
            benchmark_only=True,
            threads=args.threads,
        )
        total_native = 46693
        est_total_sec = total_native / res["rate"] if res["rate"] > 0 else 0
        est_total_min = est_total_sec / 60
        print("\n=== Benchmark Summary ===")
        print(f"Processed: {res['processed']} records in {res['elapsed_seconds']:.2f}s")
        print(f"Throughput: {res['rate']:.1f} records/sec ({1000 / res['rate']:.1f} ms/record)")
        print(f"Estimated full run for {total_native} records: {est_total_min:.1f} minutes ({est_total_min / 60:.2f} hours)")
        return 0

    index_manuals(
        db_path=args.db,
        qdrant_url=args.qdrant_url,
        collection_name=args.collection,
        batch_size=args.batch_size,
        max_length=args.max_length,
        limit=args.limit,
        threads=args.threads,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
