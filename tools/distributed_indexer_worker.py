#!/usr/bin/env python3
"""
Distributed Indexing Volunteer Worker for Aegis Sovereign Manuals (Finding O1).
Fetches un-indexed batches from coordinator, generates dense (Gemma ONNX) and sparse (BM25)
embeddings on volunteer hardware (e.g. desktop RTX 5070 / Ryzen 5700X3D), and posts results back.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from fastembed import SparseTextEmbedding


def load_gemma_session(model_path: str, num_threads: int = 8, provider: str = "CPUExecutionProvider") -> tuple[ort.InferenceSession, Any]:
    print(f"Loading ONNX model from: {model_path} with {provider} ({num_threads} threads)...")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = num_threads
    opts.inter_op_num_threads = 1
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    sess = ort.InferenceSession(model_path, opts, providers=[provider])
    return sess


def run_worker(
    hub_url: str,
    model_dir: str,
    batch_size: int = 64,
    threads: int = 8,
    provider: str = "CPUExecutionProvider",
    worker_id: str = "desktop-worker",
):
    model_path = os.path.join(model_dir, "model_q4.onnx")
    tok_path = os.path.join(model_dir, "tokenizer.json")

    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")
    if not os.path.isfile(tok_path):
        raise FileNotFoundError(f"Tokenizer file not found: {tok_path}")

    print(f"[{worker_id}] Initializing Tokenizer...")
    tok = Tokenizer.from_file(tok_path)
    tok.enable_truncation(max_length=512)

    sess = load_gemma_session(model_path, num_threads=threads, provider=provider)
    empty_feat = np.zeros((0, 512), dtype=np.float32)

    print(f"[{worker_id}] Initializing BM25 Sparse Embedding Engine...")
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

    print(f"[{worker_id}] Connecting to Coordinator at {hub_url}...")

    total_processed = 0
    t_start = time.time()

    while True:
        # 1. Fetch work
        work_url = f"{hub_url}/work?limit={batch_size}"
        try:
            req = urllib.request.Request(work_url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[{worker_id}] Failed to contact coordinator ({e}). Retrying in 3s...")
            time.sleep(3)
            continue

        if data.get("done"):
            print(f"[{worker_id}] Coordinator reported all work complete! Finished {total_processed} items.")
            break

        if data.get("waiting"):
            time.sleep(1)
            continue

        batch = data.get("batch", [])
        lease_id = data.get("lease_id", "")
        if not batch:
            time.sleep(1)
            continue

        t_batch_start = time.time()

        # 2. Dense Gemma ONNX embedding
        dense_vecs = []
        for r in batch:
            doc_title = r["title"] or "none"
            content_snippet = (r["content"] or "")[:1500]
            formatted_text = f"title: {doc_title} | text: {content_snippet}"
            
            ids = np.array([tok.encode(formatted_text).ids], dtype=np.int64)
            inputs = {
                "input_ids": ids,
                "attention_mask": np.ones_like(ids),
                "image_features": empty_feat,
                "video_features": empty_feat,
                "audio_features": empty_feat,
            }
            out = sess.run(None, inputs)
            emb_768 = out[1][0][:768]
            norm = np.linalg.norm(emb_768)
            if norm > 0:
                emb_768 = emb_768 / norm
            dense_vecs.append(emb_768.tolist())

        # 3. Sparse BM25 embedding
        sparse_texts = [f"{r['title'] or ''}\n{(r['content'] or '')[:2000]}" for r in batch]
        sparse_res = list(sparse_model.embed(sparse_texts))

        # 4. Construct point structs
        points = []
        for r, d_vec, sp_emb in zip(batch, dense_vecs, sparse_res):
            meta_json = {}
            if r.get("metadata"):
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
            points.append({
                "id": r["id"],
                "dense": d_vec,
                "sparse": {
                    "indices": sp_emb.indices.tolist(),
                    "values": sp_emb.values.tolist(),
                },
                "payload": payload,
            })

        # 5. Submit work back to Coordinator
        submit_url = f"{hub_url}/submit"
        payload_data = json.dumps({
            "lease_id": lease_id,
            "worker_id": worker_id,
            "points": points,
        }).encode("utf-8")

        submit_req = urllib.request.Request(
            submit_url,
            data=payload_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(submit_req, timeout=30) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[{worker_id}] Error submitting batch ({e}). Retrying...")
            time.sleep(2)
            continue

        total_processed += len(batch)
        batch_duration = time.time() - t_batch_start
        batch_rate = len(batch) / batch_duration if batch_duration > 0 else 0
        overall_rate = total_processed / (time.time() - t_start)
        print(
            f"[{worker_id}] Completed batch of {len(batch)} in {batch_duration:.2f}s "
            f"({batch_rate:.1f} rec/s) | Total done: {total_processed} ({overall_rate:.1f} rec/s)"
        )

    print(f"[{worker_id}] Finished! Total records processed: {total_processed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hub", type=str, default="http://127.0.0.1:8799", help="Coordinator URL")
    parser.add_argument("--model-dir", type=str, required=True, help="Directory containing model_q4.onnx and tokenizer.json")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size (default 64)")
    parser.add_argument("--threads", type=int, default=8, help="Threads for ONNX (default 8)")
    parser.add_argument("--provider", type=str, default="CPUExecutionProvider", choices=["CPUExecutionProvider", "DmlExecutionProvider"])
    parser.add_argument("--worker-id", type=str, default="worker-1", help="Identifier for this worker instance")
    args = parser.parse_args()

    run_worker(
        hub_url=args.hub,
        model_dir=args.model_dir,
        batch_size=args.batch_size,
        threads=args.threads,
        provider=args.provider,
        worker_id=args.worker_id,
    )
