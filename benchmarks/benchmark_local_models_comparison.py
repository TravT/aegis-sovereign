#!/usr/bin/env python3
"""
Comparative Benchmark: Local Downloaded CPU Models on Dell Latitude 7390.
Compares:
1. Microsoft Phi-3 Mini 4K Instruct Q4 (3.8B parameters via llama.cpp on port 8085)
2. Alibaba Qwen 2.5 1.5B Instruct Q4 (1.5B parameters via Ollama on port 11434)
3. Aegis Deterministic Extractive Synthesizer (0-LLM Signpost Protocol)

Query: "What are the first steps on the commissioning of the PCF?"
"""

import json
import os
import sys
import time
from pathlib import Path

# Add dev/aegis-sovereign-appliance to path
APP_ROOT = Path("/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance")
sys.path.insert(0, str(APP_ROOT))

from core.server import create_app
from desktop.daemon.nano_runner import NanoRunner


def run_benchmark():
    print("=" * 80)
    print("🚀 AEGIS SOVEREIGN: LOCAL MODEL HEAD-TO-HEAD BENCHMARK")
    print("Hardware: Dell Latitude 7390 (Intel Core i5-8350U @ 1.70GHz, 4C/8T)")
    print("Corpus: 48,664 Verified Huawei & Homelab Records (sovereign_router.db)")
    print("=" * 80)

    manager = create_app()
    query = "What are the first steps on the commissioning of the PCF?"
    print(f"\nTarget Query: {query!r}\n")

    # Retrieve context from vault
    route_res = manager.route_and_execute(
        query=query,
        limit=4,
        force_synthesize=False,  # Raw context retrieval first
    )
    records = route_res.get("records") or route_res.get("results") or []
    graph_dossier = route_res.get("graph_dossier")
    print(f"Retrieved {len(records)} relevant chunks from FTS5 vault.")
    for idx, r in enumerate(records[:3], 1):
        print(f"  [{idx}] {r.get('title')} | Score: {r.get('score', 0.88):.2f}")

    runner = NanoRunner(
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen2.5:1.5b",
        llama_cpp_url="http://127.0.0.1:8085",
        llama_cpp_model="Phi-3-mini-4k-instruct-q4",
    )

    results = {}

    # 1. Benchmark llama.cpp (Phi-3 Mini 3.8B)
    print("\n" + "-" * 80)
    print("🧠 [1/3] Benchmarking llama.cpp — Microsoft Phi-3 Mini 4K Instruct (3.8B GGUF)...")
    print("Executing on port 8085 (OpenAI-compatible /v1/chat/completions)...")
    t0 = time.perf_counter()
    phi3_res = runner.synthesize(
        query=query,
        chunks=records,
        graph_dossier=graph_dossier,
        prefer_engine="llama-cpp",
    )
    phi3_elapsed = time.perf_counter() - t0
    print(f"  Status: {phi3_res.execution_mode} ({phi3_res.model})")
    print(f"  Latency: {phi3_elapsed:.2f}s | Generated: {phi3_res.tokens_generated} tokens (~{phi3_res.tokens_generated / max(0.1, phi3_elapsed):.1f} tok/s)")
    print("\n--- Phi-3 Mini (3.8B) Output ---")
    print(phi3_res.answer)
    results["phi3_mini_3_8b"] = {
        "model": "Microsoft Phi-3-mini-4k-instruct-q4 (3.8B)",
        "engine": "llama.cpp (port 8085)",
        "latency_seconds": round(phi3_elapsed, 2),
        "tokens_generated": phi3_res.tokens_generated,
        "tokens_per_second": round(phi3_res.tokens_generated / max(0.1, phi3_elapsed), 2),
        "execution_mode": phi3_res.execution_mode,
        "answer": phi3_res.answer,
    }

    # 2. Benchmark Ollama (Qwen 2.5 1.5B)
    print("\n" + "-" * 80)
    print("⚡ [2/3] Benchmarking Ollama — Alibaba Qwen 2.5 Instruct (1.5B Q4_K_M)...")
    print("Executing on port 11434 (/api/generate)...")
    t0 = time.perf_counter()
    qwen_res = runner.synthesize(
        query=query,
        chunks=records,
        graph_dossier=graph_dossier,
        prefer_engine="ollama",
    )
    qwen_elapsed = time.perf_counter() - t0
    print(f"  Status: {qwen_res.execution_mode} ({qwen_res.model})")
    print(f"  Latency: {qwen_elapsed:.2f}s | Generated: {qwen_res.tokens_generated} tokens (~{qwen_res.tokens_generated / max(0.1, qwen_elapsed):.1f} tok/s)")
    print("\n--- Qwen 2.5 (1.5B) Output ---")
    print(qwen_res.answer)
    results["qwen2_5_1_5b"] = {
        "model": "Alibaba Qwen 2.5 Instruct (1.5B)",
        "engine": "Ollama (port 11434)",
        "latency_seconds": round(qwen_elapsed, 2),
        "tokens_generated": qwen_res.tokens_generated,
        "tokens_per_second": round(qwen_res.tokens_generated / max(0.1, qwen_elapsed), 2),
        "execution_mode": qwen_res.execution_mode,
        "answer": qwen_res.answer,
    }

    # 3. Benchmark Deterministic Extractive Synthesizer (0-LLM Fallback)
    print("\n" + "-" * 80)
    print("⚡ [3/3] Benchmarking Deterministic Extractive Synthesizer (Signpost Protocol 0-LLM)...")
    t0 = time.perf_counter()
    ext_res = runner.synthesize(
        query=query,
        chunks=records,
        graph_dossier=graph_dossier,
        use_ollama=False,
        prefer_engine="none",
    )
    ext_elapsed = time.perf_counter() - t0
    print(f"  Status: {ext_res.execution_mode} ({ext_res.model})")
    print(f"  Latency: {ext_elapsed * 1000.0:.2f}ms | Generated: {ext_res.tokens_generated} tokens")
    print("\n--- Deterministic Extractive Signpost Output ---")
    print(ext_res.answer)
    results["deterministic_extractive"] = {
        "model": "Aegis Deterministic Signpost Synthesizer",
        "engine": "Local In-Process Python AST (0-LLM)",
        "latency_seconds": round(ext_elapsed, 4),
        "tokens_generated": ext_res.tokens_generated,
        "execution_mode": ext_res.execution_mode,
        "answer": ext_res.answer,
    }

    # Save output to JSON
    out_path = APP_ROOT / "benchmarks" / "reports" / "local_models_pcf_comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[✓] Results saved to: {out_path}")


if __name__ == "__main__":
    run_benchmark()
