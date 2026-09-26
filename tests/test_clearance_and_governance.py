#!/usr/bin/env python3
"""
Comprehensive Security Clearance & Governance Test Suite for Aegis Sovereign Knowledge Appliance.

Tests:
1. Security Clearance Pre-Filtering Engine (MAC):
   - 4 Levels: PUBLIC=0, INTERNAL=1, CONFIDENTIAL=2, RESTRICTED=3.
   - Zero Post-Filtering: Qdrant payload filter enforcement.
   - Graph Inference Prevention: SQLite WAL entities & relations pre-filtering.
2. Multi-Tier Resource Plan Enforcer (PlanEnforcer):
   - Tier definitions: free, pro, enterprise.
   - Volume caps (100 documents on Free, unlimited on Pro/Enterprise).
   - Feature gating (Free restricted to Level 1 flash_needle, CPU only; Pro unlocks Level 2/3, Multimodal CLIP).
3. 5 High-Signal Executive Knobs in ContextCondenser:
   - analytical_depth routing (flash_needle, relational_audit, deep_synthesis).
   - evidence_grounding (verbatim_footnotes vs executive_abstract).
   - include_visual_plates (multimodal plate retrieval toggle).
   - user_clearance (security level pre-filtering).
   - critical_posture (neutral, compliance_auditor, scholarly).
"""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path

import pytest

# Ensure aegis-sovereign-appliance is in sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from core.security import (
    ClearanceLevel,
    PlanTier,
    PlanEnforcer,
    PlanLimitExceededError,
    FeatureNotAllowedError,
)
from core.chunker import parse_and_chunk_markdown, MarkdownChunk
from core.graph.store import GraphStore
from core.proxy.context_condenser import ContextCondenser, OptimizationResult
from core.search.searcher import HybridSearcher


# ==============================================================================
# 1. Security Clearance Enums & Parsing Tests
# ==============================================================================

def test_clearance_level_hierarchy_and_parsing():
    """Verify clearance level values and hierarchical authorizations."""
    assert ClearanceLevel.PUBLIC.value == 0
    assert ClearanceLevel.INTERNAL.value == 1
    assert ClearanceLevel.CONFIDENTIAL.value == 2
    assert ClearanceLevel.RESTRICTED.value == 3

    # Ordering
    assert ClearanceLevel.PUBLIC < ClearanceLevel.INTERNAL < ClearanceLevel.CONFIDENTIAL < ClearanceLevel.RESTRICTED

    # From string parsing
    assert ClearanceLevel.from_string("public") == ClearanceLevel.PUBLIC
    assert ClearanceLevel.from_string("INTERNAL") == ClearanceLevel.INTERNAL
    assert ClearanceLevel.from_string("Confidential") == ClearanceLevel.CONFIDENTIAL
    assert ClearanceLevel.from_string("restricted") == ClearanceLevel.RESTRICTED
    assert ClearanceLevel.from_string(2) == ClearanceLevel.CONFIDENTIAL

    # Authorized levels list for pre-filtering
    assert ClearanceLevel.PUBLIC.authorized_levels() == [0]
    assert ClearanceLevel.INTERNAL.authorized_levels() == [0, 1]
    assert ClearanceLevel.CONFIDENTIAL.authorized_levels() == [0, 1, 2]
    assert ClearanceLevel.RESTRICTED.authorized_levels() == [0, 1, 2, 3]

    assert ClearanceLevel.get_authorized_levels("public") == [0]
    assert ClearanceLevel.get_authorized_levels("internal") == [0, 1]
    assert ClearanceLevel.get_authorized_levels("confidential") == [0, 1, 2]
    assert ClearanceLevel.get_authorized_levels("restricted") == [0, 1, 2, 3]


# ==============================================================================
# 2. Markdown Chunker Clearance Inheritance & Override Tests
# ==============================================================================

def test_chunker_clearance_inheritance_and_overrides():
    """Verify document-level clearance inheritance and chunk/section-level override."""
    doc_content = """---
title: Confidential Acquisition Plan
clearance_level: confidential
---

# Executive Summary
This section inherits confidential clearance from frontmatter.

# Section with Inline Override
<!-- clearance: restricted -->
This paragraph contains restricted sovereign deal terms.

# Public Disclosures
[clearance: public]
This paragraph is safe for public release.
"""
    chunks = parse_and_chunk_markdown(doc_content, max_chunk_chars=200)
    assert len(chunks) >= 3

    # First section should inherit doc-level CONFIDENTIAL (2)
    assert chunks[0].clearance_level == ClearanceLevel.CONFIDENTIAL.value

    # Second section should have overridden RESTRICTED (3)
    restricted_chunks = [c for c in chunks if "restricted sovereign deal terms" in c.text]
    assert len(restricted_chunks) == 1
    assert restricted_chunks[0].clearance_level == ClearanceLevel.RESTRICTED.value

    # Third section should have overridden PUBLIC (0)
    public_chunks = [c for c in chunks if "safe for public release" in c.text]
    assert len(public_chunks) == 1
    assert public_chunks[0].clearance_level == ClearanceLevel.PUBLIC.value


# ==============================================================================
# 3. SQLite WAL Graph Store: Graph Inference Prevention Tests
# ==============================================================================

def test_graph_store_clearance_prefiltering():
    """Verify that SQLite WAL graph queries strictly enforce max_clearance.
    Ensures zero post-filtering and prevents graph inference attacks.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = GraphStore(db_path=db_path)

        # Insert entities with different clearance levels
        # Entity 1: Public Company (L0)
        e1_id = store.insert_entity("Alpha Corp", "company", "Alpha Corp Public", clearance_level=ClearanceLevel.PUBLIC.value)
        # Entity 2: Internal Project (L1)
        e2_id = store.insert_entity("Project Falcon", "project", "Internal Project Falcon", clearance_level=ClearanceLevel.INTERNAL.value)
        # Entity 3: Confidential Merger Target (L2)
        e3_id = store.insert_entity("Target Beta", "company", "Confidential Target Beta", clearance_level=ClearanceLevel.CONFIDENTIAL.value)
        # Entity 4: Restricted Sovereign Asset (L3)
        e4_id = store.insert_entity("Black Vault", "asset", "Restricted Black Vault", clearance_level=ClearanceLevel.RESTRICTED.value)

        # Insert relations with varying clearances
        # Alpha Corp -> Project Falcon (INTERNAL = 1)
        store.insert_relation(e1_id, e2_id, "operates", clearance_level=ClearanceLevel.INTERNAL.value)
        # Project Falcon -> Target Beta (CONFIDENTIAL = 2)
        store.insert_relation(e2_id, e3_id, "evaluates", clearance_level=ClearanceLevel.CONFIDENTIAL.value)
        # Target Beta -> Black Vault (RESTRICTED = 3)
        store.insert_relation(e3_id, e4_id, "custodies", clearance_level=ClearanceLevel.RESTRICTED.value)

        # Index document records with clearances
        doc_pub = store.index_document(corpus="wiki", doc_identifier="alpha_overview", title="Alpha Corp Overview", clearance_level=ClearanceLevel.PUBLIC.value)
        doc_conf = store.index_document(corpus="wiki", doc_identifier="beta_valuation", title="Target Beta Valuation", clearance_level=ClearanceLevel.CONFIDENTIAL.value)

        # --- Test Public (L0) Clearance ---
        public_neighbors = store.get_entity_neighborhood("Alpha Corp", max_clearance=ClearanceLevel.PUBLIC.value)
        # With public clearance, the relation to Project Falcon (L1) MUST NOT be returned!
        assert len(public_neighbors["neighbors"]) == 0, "Public user should not see internal edges (graph inference prevention)"

        # --- Test Internal (L1) Clearance ---
        internal_neighbors = store.get_entity_neighborhood("Alpha Corp", max_clearance=ClearanceLevel.INTERNAL.value)
        assert len(internal_neighbors["neighbors"]) == 1
        assert internal_neighbors["neighbors"][0]["entity"]["name"] == "Project Falcon"
        # From Project Falcon, should not see Target Beta (L2)
        falcon_internal = store.get_entity_neighborhood("Project Falcon", max_clearance=ClearanceLevel.INTERNAL.value)
        falcon_names = [n["entity"]["name"] for n in falcon_internal["neighbors"]]
        assert "Alpha Corp" in falcon_names
        assert "Target Beta" not in falcon_names

        # --- Test Confidential (L2) Clearance ---
        confidential_neighbors = store.get_entity_neighborhood("Project Falcon", max_clearance=ClearanceLevel.CONFIDENTIAL.value)
        target_names = [n["entity"]["name"] for n in confidential_neighbors["neighbors"]]
        assert "Target Beta" in target_names
        # But from Target Beta, should NOT see Black Vault (L3)
        beta_neighbors = store.get_entity_neighborhood("Target Beta", max_clearance=ClearanceLevel.CONFIDENTIAL.value)
        beta_targets = [n["entity"]["name"] for n in beta_neighbors["neighbors"]]
        assert "Black Vault" not in beta_targets, "Confidential user must not see restricted sovereign asset"

        # --- Test Restricted (L3) Clearance ---
        restricted_neighbors = store.get_entity_neighborhood("Target Beta", max_clearance=ClearanceLevel.RESTRICTED.value)
        r_targets = [n["entity"]["name"] for n in restricted_neighbors["neighbors"]]
        assert "Black Vault" in r_targets

        # --- Test Multi-Hop Path with Clearance Gate ---
        # Path from Alpha Corp to Target Beta requires L2 (Confidential)
        path_l1 = store.find_multi_hop_path("Alpha Corp", "Target Beta", max_hops=3, max_clearance=ClearanceLevel.INTERNAL.value)
        assert len(path_l1) == 0, "Path through confidential nodes/edges must be invisible to internal clearance"

        path_l2 = store.find_multi_hop_path("Alpha Corp", "Target Beta", max_hops=3, max_clearance=ClearanceLevel.CONFIDENTIAL.value)
        assert len(path_l2) == 2  # Alpha Corp -> Project Falcon -> Target Beta (2 edges)

        # --- Test Dossier Compilation Pre-Filtering ---
        dossier_public = store.compile_dossier("Alpha Corp", max_clearance=ClearanceLevel.PUBLIC.value)
        assert dossier_public["entity"] is not None
        assert len(dossier_public["relations"]) == 0

        dossier_restricted = store.compile_dossier("Alpha Corp", max_clearance=ClearanceLevel.RESTRICTED.value)
        assert len(dossier_restricted["relations"]) >= 1

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# ==============================================================================
# 4. Multi-Tier Resource Plan Enforcer (PlanEnforcer) Tests
# ==============================================================================

def test_plan_enforcer_free_tier():
    """Verify Free plan restrictions:
    - Max 100 documents
    - CPU inference only
    - Analytical depth restricted to flash_needle (Level 1)
    - Multimodal CLIP disallowed
    - RAPTOR & Relational Graph disallowed
    """
    free_enforcer = PlanEnforcer(tier=PlanTier.FREE, current_doc_count=50)
    assert free_enforcer.max_documents == 100
    assert free_enforcer.can_use_device("cpu") is True
    assert free_enforcer.can_use_device("cuda") is False

    # Allowed depth
    assert free_enforcer.is_depth_allowed("flash_needle") is True
    assert free_enforcer.is_depth_allowed("relational_audit") is False
    assert free_enforcer.is_depth_allowed("deep_synthesis") is False

    # Gated features
    assert free_enforcer.is_feature_allowed("multimodal_clip") is False
    assert free_enforcer.is_feature_allowed("raptor_clustering") is False
    assert free_enforcer.is_feature_allowed("cluster_delegation") is False

    # Feature assertion should raise FeatureNotAllowedError
    with pytest.raises(FeatureNotAllowedError) as exc_info:
        free_enforcer.assert_feature_allowed("multimodal_clip")
    assert "multimodal_clip" in str(exc_info.value)

    with pytest.raises(FeatureNotAllowedError) as exc_info:
        free_enforcer.assert_depth_allowed("deep_synthesis")
    assert "deep_synthesis" in str(exc_info.value)

    # Document limit assertion
    free_enforcer.assert_can_ingest(50)  # Total 100 <= 100 OK
    with pytest.raises(PlanLimitExceededError) as exc_info:
        free_enforcer.assert_can_ingest(51)  # Total 101 > 100 Exceeded
    assert "Document cap exceeded" in str(exc_info.value)


def test_plan_enforcer_pro_tier():
    """Verify Pro plan features:
    - Unlimited documents
    - CUDA/GPU allowed
    - Analytical depths: flash_needle, relational_audit, deep_synthesis
    - Multimodal CLIP and RAPTOR allowed
    - Cluster delegation disallowed
    """
    pro_enforcer = PlanEnforcer(tier=PlanTier.PRO, current_doc_count=5000)
    assert pro_enforcer.max_documents is None
    assert pro_enforcer.can_use_device("cpu") is True
    assert pro_enforcer.can_use_device("cuda") is True

    # Depths allowed
    assert pro_enforcer.is_depth_allowed("flash_needle") is True
    assert pro_enforcer.is_depth_allowed("relational_audit") is True
    assert pro_enforcer.is_depth_allowed("deep_synthesis") is True

    # Features allowed
    assert pro_enforcer.is_feature_allowed("multimodal_clip") is True
    assert pro_enforcer.is_feature_allowed("raptor_clustering") is True
    assert pro_enforcer.is_feature_allowed("graph_traversal") is True

    # Enterprise feature disallowed on Pro
    assert pro_enforcer.is_feature_allowed("cluster_delegation") is False
    with pytest.raises(FeatureNotAllowedError):
        pro_enforcer.assert_feature_allowed("cluster_delegation")

    # Ingestion check always passes
    pro_enforcer.assert_can_ingest(100000)


def test_plan_enforcer_enterprise_tier():
    """Verify Enterprise plan unlocks everything including cluster delegation."""
    ent_enforcer = PlanEnforcer(tier=PlanTier.ENTERPRISE)
    assert ent_enforcer.is_feature_allowed("cluster_delegation") is True
    assert ent_enforcer.is_feature_allowed("custom_ontologies") is True
    assert ent_enforcer.is_feature_allowed("multimodal_clip") is True


# ==============================================================================
# 5. Hybrid Searcher: Pre-Filtering MAC Invariant Tests
# ==============================================================================

class MockPoint:
    def __init__(self, pid, score, payload):
        self.id = pid
        self.score = score
        self.payload = payload


class MockQdrantClient:
    """Mock Qdrant client that verifies pre-filtering query_filter must condition."""
    def __init__(self):
        self.last_query_filter = None

    def query_points(self, collection_name, query, query_filter=None, limit=10, **kwargs):
        self.last_query_filter = query_filter
        # Simulate pre-filtered database results
        # In real Qdrant, points are filtered before ranking
        authorized_levels = [0]
        if query_filter and query_filter.must:
            for cond in query_filter.must:
                if hasattr(cond, 'key') and cond.key == "clearance_level":
                    authorized_levels = cond.match.any

        results = []
        if 0 in authorized_levels:
            results.append(MockPoint(1, 0.95, {"clearance_level": 0, "text": "Public Record Alpha", "doc_title": "Doc 1"}))
        if 1 in authorized_levels:
            results.append(MockPoint(2, 0.90, {"clearance_level": 1, "text": "Internal Memo Beta", "doc_title": "Doc 2"}))
        if 2 in authorized_levels:
            results.append(MockPoint(3, 0.85, {"clearance_level": 2, "text": "Confidential Ledger Gamma", "doc_title": "Doc 3"}))
        if 3 in authorized_levels:
            results.append(MockPoint(4, 0.80, {"clearance_level": 3, "text": "Restricted Sovereign Protocol Delta", "doc_title": "Doc 4"}))

        class MockResponse:
            def __init__(self, points):
                self.points = points
        return MockResponse(results[:limit])


def test_searcher_mac_prefiltering():
    """Verify HybridSearcher constructs and passes mandatory access control pre-filters."""
    mock_client = MockQdrantClient()
    searcher = HybridSearcher(qdrant_target="http://127.0.0.1:6333", client=mock_client)

    class MockEmbedding:
        def tolist(self):
            return [0.1] * 384

    class MockDenseModel:
        def embed(self, texts):
            return [MockEmbedding()]

    class MockSparseModel:
        def embed(self, texts):
            import numpy as np
            class SparseObj:
                indices = np.array([1, 2])
                values = np.array([0.5, 0.5])
            return [SparseObj()]

    searcher._dense_model = MockDenseModel()
    searcher._sparse_model = MockSparseModel()

    # Case 1: Public clearance search
    results_pub = searcher.search(
        query="test query",
        limit=5,
        user_clearance="public",
        analytical_depth="flash_needle"
    )
    # Verify filter was passed to Qdrant
    q_filter = mock_client.last_query_filter
    assert q_filter is not None
    assert len(q_filter.must) == 1
    cond = q_filter.must[0]
    assert cond.key == "clearance_level"
    assert cond.match.any == [0]

    # Verify results contain ONLY public (clearance 0)
    for hit in results_pub:
        assert hit["payload"]["clearance_level"] == 0
        assert "Restricted" not in hit["payload"]["text"]
        assert "Confidential" not in hit["payload"]["text"]

    # Case 2: Confidential clearance search (levels 0, 1, 2)
    results_conf = searcher.search(
        query="test query",
        limit=5,
        user_clearance="confidential",
        analytical_depth="relational_audit"
    )
    q_filter_conf = mock_client.last_query_filter
    cond_conf = q_filter_conf.must[0]
    assert cond_conf.match.any == [0, 1, 2]

    conf_levels = [hit["payload"]["clearance_level"] for hit in results_conf]
    assert 0 in conf_levels
    assert 1 in conf_levels
    assert 2 in conf_levels
    assert 3 not in conf_levels, "Restricted (3) must never be returned to confidential clearance"



# ==============================================================================
# 6. ContextCondenser: 5 Executive Knobs & Plan Gating Integration Tests
# ==============================================================================

class MockClearanceSearcher:
    """Mock searcher returning hits tagged with clearance levels."""
    def __init__(self):
        pass

    def search(self, query, limit=5, user_clearance="public", analytical_depth="flash_needle", **kwargs):
        cl = ClearanceLevel.from_string(user_clearance)
        allowed_levels = cl.get_authorized_levels()
        all_hits = [
            {"id": "c1", "text": "Public notice regarding taxes.", "score": 0.85, "clearance_level": 0, "metadata": {"doc_title": "Tax Notice", "page": 1}},
            {"id": "c2", "text": "Internal operational guideline for Q3.", "score": 0.80, "clearance_level": 1, "metadata": {"doc_title": "Ops Guide", "page": 3}},
            {"id": "c3", "text": "Confidential EBITDA projection and cap table.", "score": 0.78, "clearance_level": 2, "metadata": {"doc_title": "Cap Table", "page": 5}},
            {"id": "c4", "text": "Restricted sovereign cryptographic key inventory.", "score": 0.75, "clearance_level": 3, "metadata": {"doc_title": "Keys", "page": 1}},
        ]
        return [h for h in all_hits if h["clearance_level"] in allowed_levels][:limit]


def test_context_condenser_5_knobs_and_evidence_grounding():
    """Verify ContextCondenser handles all 5 Executive Knobs correctly:
    1. analytical_depth
    2. evidence_grounding (verbatim_footnotes vs executive_abstract)
    3. include_visual_plates
    4. user_clearance
    5. critical_posture (neutral, compliance_auditor, scholarly)
    """
    searcher = MockClearanceSearcher()
    condenser = ContextCondenser(searcher=searcher, plan_tier="pro")

    # Run with verbatim footnotes & compliance auditor
    res = condenser.optimize(
        query="Auditar obrigações tributárias e ativos confidenciais",
        user_clearance="confidential",
        analytical_depth="relational_audit",
        evidence_grounding="verbatim_footnotes",
        include_visual_plates=True,
        critical_posture="compliance_auditor",
        max_chunks=5,
    )

    assert isinstance(res, OptimizationResult)
    assert res.user_clearance == "confidential"
    assert res.analytical_depth == "relational_audit"
    assert res.evidence_grounding == "verbatim_footnotes"
    assert res.critical_posture == "compliance_auditor"
    assert res.include_visual_plates is True

    # Citations must NOT contain Restricted (level 3)
    for c in res.citations:
        assert c.get("clearance_level", 0) <= 2

    # Verbatim footnotes check
    assert "EVIDÊNCIA AUDITADA" in res.optimized_context or "EVIDÊNCIAS AUDITADAS" in res.optimized_context

    # Compliance Auditor Posture in answer synthesis
    assert "POSTURA CRÍTICA: AUDITOR DE RISCO E CONFORMIDADE" in res.answer_synthesis
    assert "PASSIVOS IDENTIFICADOS" in res.answer_synthesis

    # Visual plates should be included when enabled on Pro tier
    assert res.visual_plates is not None
    assert len(res.visual_plates) > 0


def test_context_condenser_postures():
    """Verify scholarly and neutral critical postures produce appropriate framing."""
    searcher = MockClearanceSearcher()
    condenser = ContextCondenser(searcher=searcher, plan_tier="pro")

    # Scholarly posture
    res_scholarly = condenser.optimize(
        query="Doutrina de governança corporativa",
        critical_posture="scholarly",
        evidence_grounding="executive_abstract",
    )
    assert "POSTURA CRÍTICA: DOUTRINÁRIA E HISTORIOGRÁFICA" in res_scholarly.answer_synthesis
    assert "LINHAGEM DOUTRINÁRIA" in res_scholarly.answer_synthesis
    assert "SÍNTESE EXECUTIVA CONSOLIDADA" in res_scholarly.optimized_context

    # Neutral posture
    res_neutral = condenser.optimize(
        query="Status geral de faturamento",
        critical_posture="neutral",
    )
    assert "RESUMO EXECUTIVO" in res_neutral.answer_synthesis


def test_context_condenser_plan_gating_enforcement():
    """Verify ContextCondenser strictly rejects Pro features on Free tier."""
    searcher = MockClearanceSearcher()
    free_condenser = ContextCondenser(searcher=searcher, plan_tier="free")

    # Free plan requesting deep_synthesis should raise FeatureNotAllowedError
    with pytest.raises(FeatureNotAllowedError):
        free_condenser.optimize(
            query="Deep analysis query",
            analytical_depth="deep_synthesis"
        )

    # Free plan requesting relational_audit should raise FeatureNotAllowedError
    with pytest.raises(FeatureNotAllowedError):
        free_condenser.optimize(
            query="Audit query",
            analytical_depth="relational_audit"
        )

    # Free plan requesting flash_needle without visual plates should succeed
    res_free = free_condenser.optimize(
        query="Quick query",
        analytical_depth="flash_needle",
        include_visual_plates=False,
    )
    assert res_free is not None
    assert res_free.analytical_depth == "flash_needle"
