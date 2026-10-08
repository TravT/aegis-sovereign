"""
Comprehensive Benchmark & Verification Suite for Vector Bridge Strategies:
- Option A: Offline Pre-computed k-NN Bridges (Tier 1: Personal Desktop)
- Option B: Dynamic Real-Time On-Demand Vector Bridges (Tier 3: Enterprise Datacenter)
- Option C: Hybrid Tiered Bridges (Tier 2: Edge Turnkey 1U)
"""

import time
import pytest
from pathlib import Path
from core.graphview.semantic_engine import SemanticBridgeEngine, TOPIC_PREFIX

ROUTER_DB_PATH = "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db"


@pytest.fixture
def engine():
    assert Path(ROUTER_DB_PATH).exists(), f"Router DB must exist at {ROUTER_DB_PATH}"
    return SemanticBridgeEngine(ROUTER_DB_PATH, threshold=0.25)


def test_strategy_a_offline_precomputation_and_retrieval(engine):
    """Option A (Tier 1 Desktop): Pre-computes k-NN matrix into SQLite table; instant query."""
    t0 = time.perf_counter()
    inserted_count = engine.compute_and_store_offline_bridges(k=3, threshold=0.25)
    indexing_time_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[Option A] Pre-computation indexed {inserted_count} bridges in {indexing_time_ms:.2f} ms")
    assert inserted_count > 0, "Must generate pre-computed semantic bridges"

    # Test retrieval latency
    t_query = time.perf_counter()
    bridges = engine.get_offline_bridges(min_similarity=0.25)
    lookup_time_ms = (time.perf_counter() - t_query) * 1000

    print(f"[Option A] Retrieved {len(bridges)} pre-computed bridges in {lookup_time_ms:.2f} ms (sub-millisecond target)")
    assert len(bridges) > 0
    assert lookup_time_ms < 50.0, f"Option A retrieval must be fast, took {lookup_time_ms:.2f} ms"

    # Verify 03 Upgrade Guide no longer points to SFFD-010034
    upgrade_bridges = [b for b in bridges if "03 Upgrade Guide" in b.source_id or "03 Upgrade Guide" in b.source_name]
    if upgrade_bridges:
        top_target = upgrade_bridges[0].target_name
        assert "SFFD-010034" not in top_target, f"Upgrade Guide must not point to SFFD-010034, got {top_target}"


def test_strategy_b_dynamic_realtime_query(engine):
    """Option B (Tier 3 Datacenter): Dynamic real-time vector search on node click."""
    source_id = "topic:REL_UPCF:path:03 Upgrade Guide"

    t0 = time.perf_counter()
    bridges = engine.query_realtime_knn_bridges(source_id, k=5, threshold=0.25)
    query_time_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[Option B] Real-time dynamic search returned {len(bridges)} bridges in {query_time_ms:.2f} ms")
    assert len(bridges) > 0, "Real-time search must find semantic matches"
    assert query_time_ms < 3000.0, f"Real-time search must complete under 3s on 15W laptop CPU, took {query_time_ms:.2f} ms"

    # Inspect targets
    target_names = [b.target_name for b in bridges]
    print(f"[Option B] Discovered targets: {target_names}")
    assert "SFFD-010034 Independent Microservice Upgrade" not in target_names
    assert any("Upgrade" in name for name in target_names), "Must discover legitimate upgrade topics"


def test_strategy_c_hybrid_tiered_retrieval(engine):
    """Option C (Tier 2 Edge 1U): Hybrid tiered retrieval."""
    source_id = "topic:REL_UPCF:path:03 Upgrade Guide"

    t0 = time.perf_counter()
    bridges = engine.query_hybrid_bridges(source_id, k=5)
    hybrid_time_ms = (time.perf_counter() - t0) * 1000

    print(f"\n[Option C] Hybrid retrieval returned {len(bridges)} bridges in {hybrid_time_ms:.2f} ms")
    assert len(bridges) > 0
    assert hybrid_time_ms < 100.0, f"Hybrid query should be fast, took {hybrid_time_ms:.2f} ms"


def test_benchmark_comparative_matrix(engine):
    """Generates structured benchmark telemetry comparing all 3 options."""
    # 1. Option A (Offline)
    t0 = time.perf_counter()
    count_a = engine.compute_and_store_offline_bridges(k=3, threshold=0.25)
    t_idx_a = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    _ = engine.get_offline_bridges_for_node("t:REL_UPCF:path:03 Upgrade Guide", k=5)
    t_query_a = (time.perf_counter() - t0) * 1000

    # 2. Option B (Dynamic)
    t_idx_b = 0.0  # 0s index time
    t0 = time.perf_counter()
    res_b = engine.query_realtime_knn_bridges("topic:REL_UPCF:path:03 Upgrade Guide", k=5, threshold=0.25)
    t_query_b = (time.perf_counter() - t0) * 1000

    # 3. Option C (Hybrid)
    t_idx_c = t_idx_a  # Macro pre-computed
    t0 = time.perf_counter()
    res_c = engine.query_hybrid_bridges("topic:REL_UPCF:path:03 Upgrade Guide", k=5)
    t_query_c = (time.perf_counter() - t0) * 1000

    print("\n" + "=" * 70)
    print("      AEGIS VECTOR BRIDGE PERFORMANCE BENCHMARK MATRIX (DELL 7390 CPU)")
    print("=" * 70)
    print(f"{'Strategy':<20} | {'Tier Alignment':<20} | {'Index Time':<12} | {'Query Latency':<14}")
    print("-" * 70)
    print(f"{'Option A (Offline)':<20} | {'Tier 1 (Desktop)':<20} | {t_idx_a:<10.1f}ms | {t_query_a:<12.2f}ms")
    print(f"{'Option B (Dynamic)':<20} | {'Tier 3 (Datacenter)':<20} | {t_idx_b:<10.1f}ms | {t_query_b:<12.2f}ms")
    print(f"{'Option C (Hybrid)':<20} | {'Tier 2 (Edge 1U)':<20} | {t_idx_c:<10.1f}ms | {t_query_c:<12.2f}ms")
    print("=" * 70)

    assert t_query_a < t_query_b, "Offline pre-computed lookup must be faster than dynamic scan"
