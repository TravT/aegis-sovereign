#!/usr/bin/env python3
"""
Distributed Indexing Coordinator for Aegis Sovereign Manuals (Finding O1).
Serves work batches from SQLite to cluster volunteer workers (e.g. desktop RTX 5070 / Ryzen 5700X3D)
and upserts completed dense+BM25 vectors directly into local Qdrant (127.0.0.1:6333).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.parse
import uuid

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

DEFAULT_DB = HUB_ROOT / "docs" / ".aegis_vault" / "sovereign_router.db"
DEFAULT_COLLECTION = "sovereign_chunks"
DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
DEFAULT_PORT = 8799


def ensure_collection(client: QdrantClient, collection_name: str = DEFAULT_COLLECTION) -> None:
    collections = {c.name for c in client.get_collections().collections}
    if collection_name not in collections:
        print(f"Creating Qdrant collection '{collection_name}' (768-d Cosine + BM25 sparse)...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config={"dense": VectorParams(size=768, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )
        for field, schema in [
            ("clearance_level", PayloadSchemaType.INTEGER),
            ("doc_identifier", PayloadSchemaType.KEYWORD),
            ("topic_id", PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=schema,
            )
        print(f"Collection '{collection_name}' created successfully with payload indexes.")
    else:
        info = client.get_collection(collection_name)
        print(f"Collection '{collection_name}' already exists with {info.points_count} points.")


def get_indexed_ids(client: QdrantClient, collection_name: str) -> set[int]:
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


class CoordinatorState:
    def __init__(self, db_path: Path, qdrant_url: str, collection_name: str):
        self.db_path = db_path
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.client = QdrantClient(url=qdrant_url)
        ensure_collection(self.client, collection_name)

        print(f"Loading already indexed point IDs from Qdrant '{collection_name}'...")
        self.already_indexed = get_indexed_ids(self.client, collection_name)
        print(f"Found {len(self.already_indexed)} points already indexed.")

        print(f"Connecting to SQLite: {db_path}...")
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        rows = cur.execute("""
            SELECT id, doc_identifier, title, content, clearance_level, metadata, topic_id
            FROM document_records
            WHERE record_kind = 'native'
            ORDER BY id ASC
        """).fetchall()
        self.total_native = len(rows)
        con.close()

        # Build work items for remaining
        self.work_queue: List[Dict[str, Any]] = []
        for r in rows:
            if r["id"] not in self.already_indexed:
                self.work_queue.append({
                    "id": r["id"],
                    "doc_identifier": r["doc_identifier"],
                    "title": r["title"] or "",
                    "content": r["content"] or "",
                    "clearance_level": int(r["clearance_level"] or 0),
                    "metadata": r["metadata"],
                    "topic_id": r["topic_id"] or "",
                })

        self.initial_needed = len(self.work_queue)
        self.processed = 0
        self.in_flight: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
        self.start_time = time.time()
        print(f"Initialized coordinator with {self.initial_needed} records to process (out of {self.total_native} native).")

    def get_work(self, limit: int = 64) -> Dict[str, Any]:
        now = time.time()
        # Check expired leases (> 180s)
        expired_leases = [lid for lid, (ts, _) in self.in_flight.items() if now - ts > 180]
        for lid in expired_leases:
            _, batch = self.in_flight.pop(lid)
            print(f"Lease {lid[:8]} expired after 180s. Requeuing {len(batch)} records.")
            self.work_queue.extend(batch)

        if not self.work_queue:
            if not self.in_flight:
                return {"done": True, "batch": []}
            # Still items in flight, wait
            return {"done": False, "batch": [], "waiting": True}

        batch = self.work_queue[:limit]
        self.work_queue = self.work_queue[limit:]
        lease_id = str(uuid.uuid4())
        self.in_flight[lease_id] = (now, batch)
        return {"done": False, "lease_id": lease_id, "batch": batch}

    def submit_work(self, lease_id: str, points_data: List[Dict[str, Any]], worker_id: str = "worker") -> Dict[str, Any]:
        t0 = time.time()
        if lease_id in self.in_flight:
            self.in_flight.pop(lease_id)

        points = []
        for p in points_data:
            points.append(
                PointStruct(
                    id=p["id"],
                    vector={
                        "dense": p["dense"],
                        "sparse": SparseVector(
                            indices=p["sparse"]["indices"],
                            values=p["sparse"]["values"],
                        ),
                    },
                    payload=p["payload"],
                )
            )

        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
            self.processed += len(points)

        upsert_time = time.time() - t0
        total_time = time.time() - self.start_time
        rate = self.processed / total_time if total_time > 0 else 0
        remaining = len(self.work_queue) + sum(len(b) for _, b in self.in_flight.values())
        eta_min = (remaining / rate / 60) if rate > 0 else 0

        print(
            f"[{self.processed}/{self.initial_needed}] (+{len(points)} from {worker_id} in {upsert_time:.2f}s upsert) | "
            f"Rate: {rate:.1f} rec/s | Remaining: {remaining} | ETA: {eta_min:.1f} min"
        )
        return {"status": "ok", "processed": len(points), "remaining": remaining}

    def is_complete(self) -> bool:
        return len(self.work_queue) == 0 and len(self.in_flight) == 0


class CoordinatorHandler(BaseHTTPRequestHandler):
    coordinator: CoordinatorState = None  # type: ignore

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress verbose standard HTTP access logs
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/work":
            qs = urllib.parse.parse_qs(parsed.query)
            limit = int(qs.get("limit", ["64"])[0])
            res = self.coordinator.get_work(limit=limit)
            body = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/submit":
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            try:
                data = json.loads(raw_body.decode("utf-8"))
                lease_id = data.get("lease_id", "")
                points = data.get("points", [])
                worker_id = data.get("worker_id", "worker")
                res = self.coordinator.submit_work(lease_id, points, worker_id)
                body = json.dumps(res).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                err_body = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err_body)
            return

        self.send_response(404)
        self.end_headers()


def run_coordinator(port: int = DEFAULT_PORT):
    state = CoordinatorState(DEFAULT_DB, DEFAULT_QDRANT_URL, DEFAULT_COLLECTION)
    if state.initial_needed == 0:
        print("All records already indexed in Qdrant! Exiting.")
        return

    CoordinatorHandler.coordinator = state
    server = ThreadingHTTPServer(("127.0.0.1", port), CoordinatorHandler)
    print(f"\n🚀 Aegis Sovereign Distributed Coordinator listening on http://127.0.0.1:{port}")
    print(f"Waiting for volunteer workers to connect...")

    try:
        while not state.is_complete():
            server.handle_request()
        print("\n🎉 ALL RECORDS SUCCESSFULLY INDEXED IN QDRANT!")
    except KeyboardInterrupt:
        print("\nShutting down coordinator...")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to listen on (default {DEFAULT_PORT})")
    args = parser.parse_args()
    run_coordinator(port=args.port)
