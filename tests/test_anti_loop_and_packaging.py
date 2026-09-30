"""
Automated Verification Suite for Unified Server Vault Graduation (`docs/.aegis_vault/`),
Cross-Domain Server Knowledge Consolidation (Huawei + Wiki/ADRs + Agent Skills),
First-Class Data Removal / Prefix Purge Lifecycle (`purge_records_by_prefix` & `purge_documents_by_prefix`),
4-Layer Anti-Self-Indexing ("Ouroboros") Loop Protection, and Turnkey Packaging (`install.sh` & `build_release_bundle.py`).
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APPLIANCE_ROOT.parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.onboarding.radar import OnboardingRadar
from core.router.query_router import SovereignQueryRouter
from core.graph.store import GraphStore
from core.security import PlanTier
from core.mcp import server as mcp_server
from core import server as core_server
from tools.build_release_bundle import create_release_bundle


PROD_VAULT_DIR = REPO_ROOT / "docs" / ".aegis_vault"
VISIBLE_SYMLINK = REPO_ROOT / "docs" / "aegis_index"
LEGACY_DATA_DIR = APPLIANCE_ROOT / "data"


def test_production_vault_graduation_and_symlinks():
    """
    Test 1: Verify /home/tlima/Enterprise_Hub/docs/.aegis_vault/ exists,
    contains .aegis-no-index, sovereign_router.db (>= 48,900 records),
    sovereign_graph.db (>= 8,500 entities), monitored_sources.json, and valid symlinks.
    """
    assert PROD_VAULT_DIR.exists() and PROD_VAULT_DIR.is_dir(), "docs/.aegis_vault/ must exist"
    assert (PROD_VAULT_DIR / "qdrant").is_dir(), "docs/.aegis_vault/qdrant/ must exist"
    assert (PROD_VAULT_DIR / "extracted_diagrams").is_dir(), "docs/.aegis_vault/extracted_diagrams/ must exist"

    sentinel = PROD_VAULT_DIR / ".aegis-no-index"
    assert sentinel.exists() and sentinel.is_file(), ".aegis-no-index sentinel must exist in docs/.aegis_vault/"
    sentinel_data = json.loads(sentinel.read_text(encoding="utf-8"))
    assert sentinel_data.get("sentinel") == ".aegis-no-index"

    # Canonical unified server databases
    assert (PROD_VAULT_DIR / "sovereign_router.db").is_file(), "sovereign_router.db must exist"
    assert (PROD_VAULT_DIR / "sovereign_graph.db").is_file(), "sovereign_graph.db must exist"
    assert (PROD_VAULT_DIR / "monitored_sources.json").is_file(), "monitored_sources.json must exist"

    # Backward-compatible symlinks inside docs/.aegis_vault/
    assert (PROD_VAULT_DIR / "sovereign_huawei_router.db").is_symlink()
    assert (PROD_VAULT_DIR / "sovereign_huawei_graph.db").is_symlink()
    assert (PROD_VAULT_DIR / "sovereign_huawei_router.db").resolve() == (PROD_VAULT_DIR / "sovereign_router.db").resolve()
    assert (PROD_VAULT_DIR / "sovereign_huawei_graph.db").resolve() == (PROD_VAULT_DIR / "sovereign_graph.db").resolve()

    # Zero split-brain server RAG database symlink
    server_rag_link = REPO_ROOT / "data" / "rag" / "graph_store.db"
    assert server_rag_link.is_symlink(), "data/rag/graph_store.db must be a symlink to docs/.aegis_vault/sovereign_graph.db"
    assert server_rag_link.resolve() == (PROD_VAULT_DIR / "sovereign_graph.db").resolve()

    # Visible symlink docs/aegis_index -> .aegis_vault
    assert VISIBLE_SYMLINK.is_symlink(), "docs/aegis_index must be a symlink"
    assert VISIBLE_SYMLINK.resolve() == PROD_VAULT_DIR.resolve()

    # Backward-compatible symlinks in dev/aegis-sovereign-appliance/data/
    for name in ("sovereign_router.db", "sovereign_graph.db", "sovereign_huawei_router.db", "sovereign_huawei_graph.db", "extracted_diagrams"):
        legacy_link = LEGACY_DATA_DIR / name
        assert legacy_link.is_symlink(), f"data/{name} must be a symlink to docs/.aegis_vault/{name}"
        assert legacy_link.resolve() == (PROD_VAULT_DIR / name).resolve()

    # Default DB resolution in core.mcp.server and core.server
    assert mcp_server.DEFAULT_ROUTER_DB == PROD_VAULT_DIR / "sovereign_router.db"
    assert mcp_server.DEFAULT_GRAPH_DB == PROD_VAULT_DIR / "sovereign_graph.db"
    assert core_server.DEFAULT_ROUTER_DB == PROD_VAULT_DIR / "sovereign_router.db"
    assert core_server.DEFAULT_GRAPH_DB == PROD_VAULT_DIR / "sovereign_graph.db"

    # Verify record counts in unified production databases
    r_conn = sqlite3.connect(str(PROD_VAULT_DIR / "sovereign_router.db"))
    doc_count = r_conn.execute("SELECT COUNT(*) FROM document_records").fetchone()[0]
    r_conn.close()
    assert doc_count >= 48900, f"Expected >= 48,900 unified router records, got {doc_count}"

    g_conn = sqlite3.connect(str(PROD_VAULT_DIR / "sovereign_graph.db"))
    entity_count = g_conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    rel_count = g_conn.execute("SELECT COUNT(*) FROM entity_relations").fetchone()[0]
    g_conn.close()
    assert entity_count >= 8500, f"Expected >= 8,500 unified graph entities, got {entity_count}"
    assert rel_count >= 19000, f"Expected >= 19,000 unified graph relations, got {rel_count}"


def test_unified_server_vault_cross_domain_queries():
    """
    Test 2: Verify the unified sovereign_router.db and sovereign_graph.db resolve
    Huawei 5G alarms (ALM-20104), Homelab Wiki ADRs (ADR-40, ADR-30), and Agent Skills (manage-sovereign-vault).
    """
    gs = GraphStore(db_path=PROD_VAULT_DIR / "sovereign_graph.db")
    router = SovereignQueryRouter(
        db_path=PROD_VAULT_DIR / "sovereign_router.db",
        graph_store=gs,
        plan=PlanTier.ENTERPRISE,
    )

    # 1. Huawei Telecom Alarm (ALM-20104)
    alm_hits = router.execute_deterministic_lookup("ALM-20104")
    assert len(alm_hits) >= 1, "ALM-20104 must be present in unified sovereign_router.db"
    assert "ALM-20104" in alm_hits[0]["doc_identifier"] or "ALM-20104" in alm_hits[0]["content"]

    # 2. Homelab Architecture Decision Record (ADR-40)
    adr_decision = router.analyze_query("ADR-40")
    assert adr_decision.extracted_identifier is not None
    assert adr_decision.extracted_identifier.normalized_value == "ADR-40"
    adr_hits = router.execute_deterministic_lookup("ADR-40")
    assert len(adr_hits) >= 1, "ADR-40 must be indexed in unified sovereign_router.db"
    assert "ADR-40" in adr_hits[0]["title"]

    # 3. Specialized Agent Skill (manage-sovereign-vault)
    skill_decision = router.analyze_query("manage-sovereign-vault")
    assert skill_decision.extracted_identifier is not None
    assert skill_decision.extracted_identifier.normalized_value == "manage-sovereign-vault"
    skill_hits = router.execute_deterministic_lookup("manage-sovereign-vault")
    assert len(skill_hits) >= 1, "manage-sovereign-vault must be indexed in unified sovereign_router.db"
    assert "manage-sovereign-vault" in skill_hits[0]["doc_identifier"]

    # 4. Verify GraphStore cross-domain dossiers
    hub_dossier = gs.compile_dossier("Enterprise_Hub")
    assert hub_dossier["entity"] is not None
    assert len(hub_dossier["relations"]) >= 50, "Enterprise_Hub must connect to skills and docs in sovereign_graph.db"

    router.close()
    gs.close()


def test_data_ingestion_and_deterministic_purge_lifecycle(tmp_path: Path):
    """
    Test 3: Verify first-class data removal / purge lifecycle:
    Ingest temporary records (`test_temp_corpus://doc1` and `test_temp_corpus://doc2`)
    into SovereignQueryRouter (B-Tree + FTS5) and GraphStore, verify they are searchable,
    then call `purge_records_by_prefix` and `purge_documents_by_prefix` and assert 0 hits remain.
    """
    r_db = tmp_path / "test_router.db"
    g_db = tmp_path / "test_graph.db"
    gs = GraphStore(db_path=g_db)
    router = SovereignQueryRouter(db_path=r_db, graph_store=gs, plan=PlanTier.ENTERPRISE)

    # Ingest temporary corpus records and permanent baseline record
    router.index_document(
        doc_identifier="test_temp_corpus://doc1",
        title="Temporary Secret Protocol X9912",
        content="Unique token ZYXX9912quantum inside temporary test corpus document one.",
        metadata={"domain": "temp_test", "source_dir": "test_temp_corpus://"},
    )
    router.index_document(
        doc_identifier="test_temp_corpus://doc2",
        title="Temporary Secret Protocol X9913",
        content="Second temporary document referencing ZYXX9912quantum.",
        metadata={"domain": "temp_test", "source_dir": "test_temp_corpus://"},
    )
    router.index_document(
        doc_identifier="permanent_corpus://keep1",
        title="Permanent Baseline Architecture",
        content="This permanent record must survive prefix purge untouched.",
        metadata={"domain": "permanent"},
    )

    gs.index_document(
        corpus="temp_test",
        doc_identifier="test_temp_corpus://doc1",
        title="Temporary Secret Protocol X9912",
        entities=[
            {"name": "TempEntity_Alpha_9912", "entity_type": "protocol"},
            {"name": "TempEntity_Beta_9912", "entity_type": "system"},
        ],
        relations=[
            {
                "source": "TempEntity_Alpha_9912",
                "target": "TempEntity_Beta_9912",
                "relation_type": "ROUTES_TO",
            }
        ],
    )

    # Verify searchable before purge (both B-Tree and FTS5 and GraphStore)
    pre_hits = router.execute_deterministic_lookup("test_temp_corpus://doc1")
    assert len(pre_hits) == 1
    fts_before = router._conn.execute(
        "SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH 'ZYXX9912quantum'"
    ).fetchone()[0]
    assert fts_before == 2

    dossier_before = gs.compile_dossier("TempEntity_Alpha_9912")
    assert dossier_before["entity"] is not None
    assert len(dossier_before["relations"]) == 1

    # Execute deterministic prefix purge
    r_purge = router.purge_records_by_prefix("test_temp_corpus://")
    g_purge = gs.purge_documents_by_prefix("test_temp_corpus://")

    assert r_purge["deleted_router_records"] == 2
    assert g_purge["deleted_graph_docs"] == 1
    assert g_purge["deleted_relations"] == 1
    assert g_purge["deleted_orphan_entities"] == 2

    # Assert 0 hits remain in document_records, document_fts, and GraphStore
    post_hits = router.execute_deterministic_lookup("test_temp_corpus://doc1")
    assert len(post_hits) == 0
    fts_after = router._conn.execute(
        "SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH 'ZYXX9912quantum'"
    ).fetchone()[0]
    assert fts_after == 0

    dossier_after = gs.compile_dossier("TempEntity_Alpha_9912")
    assert dossier_after.get("entity") is None

    # Assert permanent corpus record is 100% intact
    keep_hits = router.execute_deterministic_lookup("permanent_corpus://keep1")
    assert len(keep_hits) == 1

    router.close()
    gs.close()


def test_onboarding_radar_and_watcher_anti_self_indexing_loop():
    """
    Test 4: Run OnboardingRadar().scan_workspace(['/home/tlima/Enterprise_Hub/docs'])
    and prove that docs/wiki is discovered while docs/.aegis_vault, docs/aegis_index,
    and docs/Hua_Docs are 100% excluded (zero self-indexing loop!).
    """
    radar = OnboardingRadar()
    assert ".aegis_vault" in radar.SKIP_DIRS
    assert "aegis_index" in radar.SKIP_DIRS
    assert "Hua_Docs" in radar.SKIP_DIRS
    assert ".db" in radar.SKIP_EXTENSIONS
    assert ".aegis-no-index" in radar.SKIP_EXTENSIONS

    docs_root = REPO_ROOT / "docs"
    candidates = radar.scan_workspace([docs_root], max_scan_seconds=15.0)
    discovered_paths = [c.path for c in candidates]

    # Prove docs/wiki is discovered
    assert any("/docs/wiki" in p for p in discovered_paths), "docs/wiki must be discovered by OnboardingRadar"

    # Prove docs/.aegis_vault, docs/aegis_index, and docs/Hua_Docs are 100% excluded
    for p in discovered_paths:
        assert ".aegis_vault" not in p, f"Self-indexing loop detected: {p}"
        assert "aegis_index" not in p, f"Symlink loop detected: {p}"
        assert "Hua_Docs" not in p, f"Hua_Docs raw archive dir should be excluded: {p}"
        assert "extracted_diagrams" not in p, f"extracted_diagrams dir should be excluded: {p}"

    # Verify Layer 4 (.gitignore) contains docs/.aegis_vault/ and docs/aegis_index
    gitignore_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "docs/.aegis_vault/" in gitignore_text
    assert "docs/aegis_index" in gitignore_text


def test_sentinel_file_prevents_indexing_in_temp_directory(tmp_path: Path):
    """
    Test 5: Test a temporary directory containing a .aegis-no-index sentinel file
    and prove OnboardingRadar skips it even if it contains .md or .pdf files.
    """
    normal_dir = tmp_path / "engineering_docs"
    normal_dir.mkdir(parents=True)
    (normal_dir / "architecture_manual.md").write_text("# Router Architecture\n", encoding="utf-8")
    (normal_dir / "spec.pdf").write_bytes(b"%PDF-1.4 dummy content")

    guarded_dir = tmp_path / "custom_vault_index"
    guarded_dir.mkdir(parents=True)
    (guarded_dir / ".aegis-no-index").write_text("{}", encoding="utf-8")
    (guarded_dir / "should_never_be_indexed.md").write_text("# Secret Index Dump\n", encoding="utf-8")
    (guarded_dir / "vector_dump.pdf").write_bytes(b"%PDF-1.4 should be skipped")
    (guarded_dir / "sovereign.db").write_bytes(b"SQLite format 3\x00")

    nested_inside_guarded = guarded_dir / "nested_docs"
    nested_inside_guarded.mkdir(parents=True)
    (nested_inside_guarded / "nested.md").write_text("# Nested\n", encoding="utf-8")

    radar = OnboardingRadar()
    candidates = radar.scan_workspace([tmp_path], max_scan_seconds=5.0)
    paths = [Path(c.path).resolve() for c in candidates]

    assert normal_dir.resolve() in paths, "Normal directory without sentinel must be discovered"
    assert guarded_dir.resolve() not in paths, "Directory with .aegis-no-index must be skipped"
    assert nested_inside_guarded.resolve() not in paths, "Subdirectories under .aegis-no-index must be skipped"


def test_turnkey_install_script_and_release_bundle_builder():
    """
    Test 6: Run ./install.sh --check-only and build_release_bundle.py --dry-run
    and verify 0 exit code and complete manifest generation (including all 15 manuals).
    """
    install_script = APPLIANCE_ROOT / "install.sh"
    res = subprocess.run(
        [str(install_script), "--check-only"],
        cwd=str(APPLIANCE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"install.sh --check-only failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "[Stage 1/6]" in res.stdout
    assert "[Stage 6/6]" in res.stdout
    assert "Prong 1 & GraphRAG Smoke PASS" in res.stdout

    bundle_script = APPLIANCE_ROOT / "tools" / "build_release_bundle.py"
    res_bundle = subprocess.run(
        [sys.executable, str(bundle_script), "--dry-run"],
        cwd=str(APPLIANCE_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_bundle.returncode == 0, f"build_release_bundle.py --dry-run failed:\n{res_bundle.stderr}"
    assert "mode=dry-run version=2.1.0" in res_bundle.stdout

    # Verify programmatic manifest structure
    dry_info = create_release_bundle(dry_run=True)
    manifest = dry_info["manifest"]
    assert manifest["version"] == "2.1.0"
    assert manifest["operator_manuals_count"] == 17  # manuals 01-17 (16: structure, 17: file-type handlers)
    assert manifest["mcp_v2_tool_schemas_count"] == 7
    assert manifest["components"]["core"] is True
    assert manifest["components"]["desktop_nano_runner"] is True
    assert manifest["components"]["web_portal"] is True
    assert manifest["components"]["sovereign_mcp_entrypoint"] is True
    assert manifest["components"]["manage_sovereign_vault_skill"] is True
    assert len(manifest["files"]) >= 80
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])
