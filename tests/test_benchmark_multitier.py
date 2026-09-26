"""
Tests for Multi-Tier Benchmark Engine & V2 Unified Multi-Scale Architecture
Validates:
- Chapter parsing and ~512-token chunking
- Tier 1 Flat RAG dense + sparse BM25 RRF scoring
- Tier 2 GraphRAG SQLite schema, dynamic entity discovery, and multi-hop BFS
- Tier 3 RAPTOR hierarchical fusion scoring and incremental DAG mutation / invalidation
- Multimodal CLIP cross-modal scoring
- V2 Unified Multi-Scale Fused Retrieval
"""

import os
import sys
import sqlite3
import pytest
from pathlib import Path

# Ensure appliance root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient

from fastembed import TextEmbedding, SparseTextEmbedding, ImageEmbedding
from benchmarks.benchmark_multitier import (
    load_and_parse_chapters,
    Tier1FlatRAG,
    Tier2GraphRAG,
    Tier3HierarchicalRAPTOR,
    MultimodalCLIPEngine,
    UnifiedMultiscaleRetriever,
    CHAPTER_ABSTRACTS_DATA,
    CORPUS_PATH,
    GRAPH_DB_PATH,
    IMAGE_MANIFEST_PATH,
    MicroChunk
)


@pytest.fixture(scope="module")
def parsed_corpus():
    assert CORPUS_PATH.exists(), f"Corpus not found at {CORPUS_PATH}"
    chapters, micro_chunks = load_and_parse_chapters(CORPUS_PATH)
    return chapters, micro_chunks


@pytest.fixture(scope="module")
def qdrant_mem():
    return QdrantClient(location=":memory:")


@pytest.fixture(scope="module")
def text_models():
    dense = TextEmbedding("BAAI/bge-small-en-v1.5")
    sparse = SparseTextEmbedding("Qdrant/bm25")
    return dense, sparse


def test_corpus_parsing(parsed_corpus):
    chapters, micro_chunks = parsed_corpus
    assert len(chapters) == 12, "Alice's Adventures in Wonderland must parse into exactly 12 chapters"
    assert len(micro_chunks) >= 80, "Must produce >= 80 micro-chunks (~512 tokens each)"

    ch1 = chapters[0]
    assert ch1["chapter_num"] == 1
    assert "Rabbit-Hole" in ch1["title"]
    assert ch1["word_count"] > 1000

    chunk0 = micro_chunks[0]
    assert chunk0.chapter_num == 1
    assert chunk0.chunk_id == "ch01_chunk00"
    assert chunk0.est_tokens > 100


def test_tier1_flat_rag_rrf(parsed_corpus, qdrant_mem, text_models):
    _, micro_chunks = parsed_corpus
    dense, sparse = text_models

    # Index first 10 chunks for fast test
    test_chunks = micro_chunks[:10]
    tier1 = Tier1FlatRAG(qdrant_mem, dense, sparse)
    tier1.index(test_chunks)

    res = tier1.search("bottle marked DRINK ME", top_k=3)
    assert res["retrieved_count"] > 0
    assert res["total_tokens"] > 0
    assert 1 in res["covered_chapters"]
    # Verify RRF score ordering
    scores = [r["score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True)


def test_tier2_graphrag_dynamic_entities(tmp_path):
    db_path = tmp_path / "test_graph.db"
    t2 = Tier2GraphRAG(db_path)
    t2.index()

    # Verify schema and row counts
    cur = t2.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM entities;")
    ent_count = cur.fetchone()[0]
    assert ent_count >= 20

    cur.execute("SELECT COUNT(*) FROM relations;")
    rel_count = cur.fetchone()[0]
    assert rel_count >= 40

    # Test Dynamic Entity Extraction without hardcoded lists
    query = "Alice was frightened when the Mad Hatter and the Queen of Hearts argued."
    found = t2.find_entities_in_text(query)
    names = [f["name"] for f in found]
    assert "Alice" in names
    assert "Mad Hatter" in names
    assert "Queen of Hearts" in names

    # Test Multi-hop BFS path tracing
    seq = ["Alice", "March Hare", "Mad Hatter", "Queen of Hearts"]
    path_res = t2.find_multi_hop_path(seq)
    assert len(path_res["path_steps"]) >= 2
    assert 7 in path_res["covered_chapters"]


def test_tier3_raptor_hierarchical_fusion(parsed_corpus, qdrant_mem, text_models):
    _, micro_chunks = parsed_corpus
    dense, sparse = text_models

    t3 = Tier3HierarchicalRAPTOR(qdrant_mem, dense, sparse)
    t3.index(micro_chunks[:15], CHAPTER_ABSTRACTS_DATA[:3])

    res = t3.search("identity crisis growing and shrinking", query_type="thematic", top_k_chapters=2, top_k_chunks=3)
    assert res["tier"] == "Tier 3: Hierarchical Tree Retrieval / RAPTOR"
    assert len(res["top_chapters"]) <= 2
    assert len(res["top_leaf_chunks"]) <= 3
    assert res["total_tokens"] > 500
    assert "[RAPTOR Layer 2: Volume Thesis]" in res["text"]
    assert "[RAPTOR Layer 1:" in res["text"]
    assert "[RAPTOR Layer 0 Grounding:" in res["text"]


def test_tier3_raptor_incremental_mutation(parsed_corpus, qdrant_mem, text_models):
    """Verifies V2 DAG Mutation & selective leaf invalidation without wiping index."""
    _, micro_chunks = parsed_corpus
    dense, sparse = text_models

    t3 = Tier3HierarchicalRAPTOR(qdrant_mem, dense, sparse)
    t3.index(micro_chunks[:15], CHAPTER_ABSTRACTS_DATA[:3])

    # Mutate Chapter 1 only
    mutated_chunk = MicroChunk(
        chunk_id="ch01_mutated_01",
        chapter_num=1,
        chapter_title="Down the Rabbit-Hole [V2 EDIT]",
        chunk_index=0,
        text="[Chapter 1: Down the Rabbit-Hole - Chunk 0]\n\nAlice found a titanium key on a platinum table.",
        raw_text="Alice found a titanium key on a platinum table.",
        word_count=10,
        est_tokens=14
    )
    mutated_abstract = {
        "chapter_num": 1,
        "title": "Down the Rabbit-Hole [V2 EDIT]",
        "key_entities": ["Alice", "Titanium Key"],
        "thematic_motifs": ["mutation", "v2"],
        "summary": "Alice discovered a futuristic titanium key."
    }

    t3.update_chapter(1, [mutated_chunk], mutated_abstract)

    # Search for mutated content
    res = t3.search("titanium key", query_type="micro", top_k_chapters=1, top_k_chunks=1)
    assert "titanium key" in res["text"].lower()
    # Ensure Chapter 2 abstract is still present in collection
    cur_pts = qdrant_mem.retrieve(collection_name=t3.layer1_col, ids=[2])
    assert len(cur_pts) == 1
    assert cur_pts[0].payload["chapter_num"] == 2


def test_multimodal_clip_cross_modal(qdrant_mem):
    vision = ImageEmbedding("Qdrant/clip-ViT-B-32-vision")
    text_clip = TextEmbedding("Qdrant/clip-ViT-B-32-text")
    mm = MultimodalCLIPEngine(qdrant_mem, vision, text_clip)

    assert IMAGE_MANIFEST_PATH.exists()
    mm.index(IMAGE_MANIFEST_PATH, CHAPTER_ABSTRACTS_DATA)

    # Text to Image
    t2i = mm.search_image_by_text("White Rabbit with pocket watch", top_k=2)
    assert len(t2i["matches"]) == 2
    assert t2i["matches"][0]["file_name"] == "alice02a.png"

    # Image to Text
    rabbit_img = str(IMAGE_MANIFEST_PATH.parent / "alice02a.png")
    i2t = mm.search_text_by_image(rabbit_img, top_k=2)
    assert len(i2t["matches"]) == 2
    assert i2t["matches"][0]["chapter"] == 1


def test_unified_multiscale_retriever(parsed_corpus, qdrant_mem, text_models, tmp_path):
    _, micro_chunks = parsed_corpus
    dense, sparse = text_models

    # Prepare engines
    t1 = Tier1FlatRAG(qdrant_mem, dense, sparse)
    t1.index(micro_chunks[:20])

    t2 = Tier2GraphRAG(tmp_path / "test_unified_graph.db")
    t2.index()

    t3 = Tier3HierarchicalRAPTOR(qdrant_mem, dense, sparse)
    t3.index(micro_chunks[:20], CHAPTER_ABSTRACTS_DATA[:3])

    retriever = UnifiedMultiscaleRetriever(t3, t2, t1)

    query = "Why did the White Rabbit cause Alice to shrink and what was on the table?"
    res = retriever.retrieve(query, top_k_chapters=2, top_k_chunks=3)

    assert res["query"] == query
    assert res["latency_ms"] > 0
    assert "White Rabbit" in res["discovered_entities"]
    assert "Alice" in res["discovered_entities"]
    assert 1 in res["covered_chapters"]
    assert "=== UNIFIED MULTI-SCALE EVIDENCE DOSSIER ===" in res["dossier_text"]
    assert "--- [RELATIONAL GRAPH TOPOLOGY] ---" in res["dossier_text"]
    assert "--- [RAPTOR HIERARCHICAL CONTEXT] ---" in res["dossier_text"]
