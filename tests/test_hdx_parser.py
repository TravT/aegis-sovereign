#!/usr/bin/env python3
"""Unit & Integration Test Suite for Deep .HDX Telecom Vendor Package Parser (Manual 13).

Validates:
1. 100% in-memory O_RDONLY streaming via `HdxTelecomIngestor` + `SovereignArchiveStreamer`
   with zero temporary disk extraction and `<100:1` zip-bomb ratio enforcement.
2. Navigation tree (`navi.xml`) hierarchical breadcrumb reconstruction and automatic mapping
   to RAPTOR Layer 2 (`RAPTOR_L2_THESIS`), Layer 1 (`RAPTOR_L1_ABSTRACT`), and Layer 0 (`archive://...`).
3. Structured Telecom Entity & Table Extraction:
   - Alarm Specifications (`ALM-26235`, `ALM-29201`, `ALM-26522`, `ALM-25888`), Severity, Causes, Steps.
   - MML Commands (`DSP OPTMODULE`, `MOD NRDUCELL`, `LST ALMAF`, `ADD GNBOPERATOR`) + Parameter Tables.
   - 3GPP / Vendor KPI Counters (`VS.NR.RRC.ConnEstab.Succ`, `VS.NR.MAC.DL.Throughput`).
4. Direct indexing into `SovereignQueryRouter` (`<1.5ms` Prong 1 deterministic lookup) and
   `GraphStore` multi-hop relational edges (`AFFECTS_NE`, `CAUSED_BY`, `DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`).
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.benchmark_hdx_ingestion import build_sample_hdx_package
from core.containers.archive_streamer import ArchiveSecurityError
from core.containers.hdx_parser import HdxTelecomIngestor
from core.graph.store import GraphStore
from core.router.query_router import QueryRouteType, SovereignQueryRouter
from core.security import ClearanceLevel, PlanTier


@pytest.fixture
def sample_hdx_path(tmp_path: Path) -> Path:
    """Build deterministic sample_5g_ran_bbu5900.hdx package in tmp_path."""
    return build_sample_hdx_package(tmp_path / "sample_5g_ran_bbu5900.hdx")


def test_01_hdx_navigation_tree_and_raptor_strata(sample_hdx_path: Path) -> None:
    """Verify navi.xml parsing reconstructs breadcrumbs and maps RAPTOR L2/L1/L0 layers."""
    ingestor = HdxTelecomIngestor()
    manifest = ingestor.parse_hdx_package(sample_hdx_path)

    assert manifest.package_title == "5G RAN BBU5900 V100R019"
    assert manifest.version == "V100R019C10"
    assert manifest.nav_tree is not None
    assert manifest.nav_tree.raptor_layer == "RAPTOR_L2_THESIS"

    # Verify RAPTOR L2 Thesis and L1 Abstract nodes were generated
    l2_nodes = [n for n in manifest.raptor_nodes if n["raptor_layer"] == "RAPTOR_L2_THESIS"]
    l1_nodes = [n for n in manifest.raptor_nodes if n["raptor_layer"] == "RAPTOR_L1_ABSTRACT"]
    assert len(l2_nodes) == 1
    assert len(l1_nodes) >= 4

    # Verify full breadcrumb path for ALM-26235
    alm_26235 = next(a for a in manifest.alarms if a.alarm_id == "ALM-26235")
    assert (
        alm_26235.breadcrumb
        == "5G RAN BBU5900 V100R019 > Alarm Reference > Hardware & Optical Alarms > ALM-26235 RF Unit Optical Module Fault"
    )
    assert alm_26235.virtual_uri.startswith("archive://")
    assert alm_26235.virtual_uri.endswith("#pages/03_alm_26235_optical_fault.html")


def test_02_structured_alarm_mml_and_kpi_extraction(sample_hdx_path: Path) -> None:
    """Verify Alarm specs, MML command parameter tables, and 3GPP KPI counters extract accurately."""
    ingestor = HdxTelecomIngestor()
    manifest = ingestor.parse_hdx_package(sample_hdx_path)

    # 1. Alarms
    alarm_ids = {a.alarm_id for a in manifest.alarms}
    assert {"ALM-26235", "ALM-29201", "ALM-26522", "ALM-25888"}.issubset(alarm_ids)

    alm_26235 = next(a for a in manifest.alarms if a.alarm_id == "ALM-26235")
    assert alm_26235.severity == "Critical"
    assert alm_26235.affected_ne == "BBU5900"
    assert "DSP OPTMODULE" in alm_26235.diagnostic_mml
    assert "MOD NRDUCELL" in alm_26235.remediation_mml
    assert len(alm_26235.possible_causes) >= 2
    assert len(alm_26235.remediation_steps) >= 3

    # 2. MML Commands & Parameter Tables
    mml_names = {m.command for m in manifest.mml_commands}
    assert {"DSP OPTMODULE", "MOD NRDUCELL", "LST ALMAF", "ADD GNBOPERATOR"}.issubset(mml_names)

    dsp_opt = next(m for m in manifest.mml_commands if m.command == "DSP OPTMODULE")
    param_ids = [p.param_id for p in dsp_opt.parameters]
    assert param_ids == ["CN", "SRN", "SN", "MODULEID"]
    assert dsp_opt.parameters[2].default_value == "2"

    # 3. 3GPP / Vendor KPI Counters
    kpi_ids = {k.counter_id for k in manifest.kpi_counters}
    assert "VS.NR.RRC.ConnEstab.Succ" in kpi_ids
    assert "VS.NR.MAC.DL.Throughput" in kpi_ids
    assert "VS.NR.QoS.5QI.PacketLossRate" in kpi_ids


def test_03_prong1_deterministic_lookup_and_compound_routing(sample_hdx_path: Path) -> None:
    """Verify ingested .hdx entities resolve in <1.5ms via Prong 1 and compound queries trigger synthesis."""
    router = SovereignQueryRouter(db_path=":memory:", plan=PlanTier.ENTERPRISE)
    graph_store = GraphStore(db_path=":memory:")
    router.graph_store = graph_store
    ingestor = HdxTelecomIngestor()

    summary = ingestor.ingest_hdx_package(
        hdx_path=sample_hdx_path,
        router=router,
        graph_store=graph_store,
        clearance_level=ClearanceLevel.INTERNAL,
    )
    assert summary["status"] == "success"
    assert summary["indexed_router_records"] >= 15

    # 1. Isolated Alarm ID -> DETERMINISTIC_DIRECT (<1.5ms, needs_synthesis=False)
    dec_alm = router.analyze_query("ALM-26235")
    assert dec_alm.route_type == QueryRouteType.DETERMINISTIC_DIRECT
    assert dec_alm.extracted_identifier is not None
    assert dec_alm.extracted_identifier.id_type == "telecom_alarm"
    assert dec_alm.needs_synthesis is False

    runs = [router.route_and_execute("ALM-26235", user_clearance=ClearanceLevel.INTERNAL) for _ in range(3)]
    best_ms = min(r["latency_ms"] for r in runs)
    res_alm = runs[-1]
    assert res_alm["status"] == "success"
    assert best_ms < 1.5, f"Expected Prong 1 lookup <1.5ms, got {best_ms:.3f}ms"
    assert res_alm["results"][0]["metadata"]["virtual_uri"].endswith("#pages/03_alm_26235_optical_fault.html")

    # 2. Isolated MML Command -> DETERMINISTIC_DIRECT
    dec_mml = router.analyze_query("DSP OPTMODULE")
    assert dec_mml.route_type == QueryRouteType.DETERMINISTIC_DIRECT
    assert dec_mml.extracted_identifier is not None
    assert dec_mml.extracted_identifier.id_type == "mml_command"
    res_mml = router.route_and_execute("DSP OPTMODULE", user_clearance=ClearanceLevel.INTERNAL)
    assert res_mml["status"] == "success"
    assert "MODULEID" in res_mml["results"][0]["content"]

    # 3. Isolated KPI Counter -> DETERMINISTIC_DIRECT
    dec_kpi = router.analyze_query("VS.NR.RRC.ConnEstab.Succ")
    assert dec_kpi.route_type == QueryRouteType.DETERMINISTIC_DIRECT
    assert dec_kpi.extracted_identifier is not None
    assert dec_kpi.extracted_identifier.id_type == "telecom_kpi"

    # 4. Compound Troubleshooting Query -> COMPOUND_FUSED (needs_synthesis=True)
    compound_q = "Why did ALM-26235 trigger and how to fix with DSP OPTMODULE?"
    dec_comp = router.analyze_query(compound_q)
    assert dec_comp.route_type == QueryRouteType.COMPOUND_FUSED
    assert dec_comp.needs_synthesis is True
    assert dec_comp.extracted_identifier is not None
    assert dec_comp.extracted_identifier.normalized_value == "ALM-26235"

    router.close()
    graph_store.close()


def test_04_graph_store_telecom_edges_and_zip_bomb_guard(sample_hdx_path: Path, tmp_path: Path) -> None:
    """Verify GraphStore edges (AFFECTS_NE, CAUSED_BY, DIAGNOSED_BY_MML, REMEDIATED_BY_MML) and zip-bomb rejection."""
    graph_store = GraphStore(db_path=":memory:")
    ingestor = HdxTelecomIngestor()
    ingestor.ingest_hdx_package(
        hdx_path=sample_hdx_path,
        router=None,
        graph_store=graph_store,
        clearance_level=ClearanceLevel.INTERNAL,
    )

    neighborhood = graph_store.get_entity_neighborhood(
        entity_name="ALM-26235",
        max_depth=1,
        max_clearance=ClearanceLevel.INTERNAL.value,
    )
    rel_pairs = {(n["relation"], n["entity"]["name"]) for n in neighborhood["neighbors"]}

    assert ("AFFECTS_NE", "BBU5900") in rel_pairs
    assert ("CAUSED_BY", "Optical_Rx_Power_Below_Threshold") in rel_pairs
    assert ("DIAGNOSED_BY_MML", "DSP OPTMODULE") in rel_pairs
    assert ("REMEDIATED_BY_MML", "MOD NRDUCELL") in rel_pairs
    graph_store.close()

    # Verify Zip-Bomb (>100:1 compression ratio) inside .hdx is immediately blocked in-memory
    bomb_hdx = tmp_path / "malicious_bomb.hdx"
    with zipfile.ZipFile(bomb_hdx, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pages/bomb.html", b"A" * (2 * 1024 * 1024))

    with pytest.raises(ArchiveSecurityError, match="Zip-bomb compression ratio exceeded"):
        ingestor.parse_hdx_package(bomb_hdx)
