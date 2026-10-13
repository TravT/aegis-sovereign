"""Finding O1 follow-up: the dense leg must never fail silently.

On 13 Oct 2026 the live server could not load EmbeddingGemma (its loader and model were not
mounted), fell back to a 384-d MiniLM query against the 768-d `sovereign_chunks` collection, the
dense query failed, and the error was swallowed: every hit was keyword-only and nothing said so.
"""
import logging
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from core.search.searcher import SovereignSearcher


class FakeClient:
    def __init__(self, dim=768, dense_error=None):
        self.dim = dim
        self.dense_error = dense_error
        self.dense_queries = []

    def collection_exists(self, name):
        return True

    def count(self, collection_name, exact=False):
        return SimpleNamespace(count=10)

    def get_collection(self, name):
        vectors = {"dense": SimpleNamespace(size=self.dim)}
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))

    def query_points(self, collection_name, query, using, query_filter, limit):
        if using == "dense":
            if self.dense_error:
                raise self.dense_error
            self.dense_queries.append(query)
            return SimpleNamespace(points=[SimpleNamespace(id="d1", score=0.9, payload={"title": "dense hit"})])
        return SimpleNamespace(points=[SimpleNamespace(id="s1", score=12.0, payload={"title": "sparse hit"})])


class FakeSparse:
    def embed(self, texts):
        yield SimpleNamespace(indices=np.array([1, 2]), values=np.array([0.5, 0.5]))


class FakeGemma:
    def __init__(self, mrl_dim=768):
        self.mrl_dim = mrl_dim

    def encode_queries(self, queries, task="search result"):
        return [[0.1] * self.mrl_dim for _ in queries]


def _searcher(client):
    s = SovereignSearcher(client=client)
    s._sparse_model = FakeSparse()
    return s


@pytest.fixture
def gemma_module(monkeypatch):
    mod = types.ModuleType("scripts.embedding_gemma_onnx")
    mod.EmbeddingGemmaONNX = FakeGemma
    monkeypatch.setitem(sys.modules, "scripts.embedding_gemma_onnx", mod)
    return mod


def test_missing_gemma_for_768d_collection_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "scripts.embedding_gemma_onnx", None)  # import fails
    with pytest.raises(RuntimeError, match="EmbeddingGemma"):
        _searcher(FakeClient(dim=768)).search("MOD SCTPPP")


def test_768d_collection_uses_gemma_and_fuses_dense_hits(gemma_module):
    client = FakeClient(dim=768)
    hits = _searcher(client).search("how to restore diameter link after peer timeout")
    assert len(client.dense_queries[0]) == 768
    assert any("dense_rank" in h["meta"] for h in hits)


def test_dense_query_error_is_logged_not_swallowed(gemma_module, caplog):
    client = FakeClient(dim=768, dense_error=ValueError("Vector dimension error"))
    with caplog.at_level(logging.ERROR, logger="core.search.searcher"):
        hits = _searcher(client).search("NGPING")
    assert [h["id"] for h in hits] == ["s1"]  # keyword results still served
    assert any("dense" in r.getMessage().lower() and r.levelno == logging.ERROR for r in caplog.records)
