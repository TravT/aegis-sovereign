"""Findings register U8: a correct hybrid answer was labelled "LOW_UNVERIFIED (0.03)".

The RRF score (rank-based, about 0.03 for any first hit) was shown as the confidence. Hits now carry a
calibrated `confidence_score` from the dense cosine (EmbeddingGemma 768-d), and the router, the server and
NanoRunner use it instead of the RRF score.
"""
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from core.search.confidence import hybrid_confidence, top_confidence
from core.search.searcher import SovereignSearcher
from desktop.daemon.nano_runner import NanoRunner


# The live OSPF question, 13 Oct: DSP OSPFPEER was dense #1 (cosine 0.8557) and sparse #5.
OSPF_HIT = {"dense_rank": 1, "dense_score": 0.855723, "sparse_rank": 5, "sparse_score": 10.67}


def test_right_answer_is_high_and_off_topic_is_below_the_floor():
    assert hybrid_confidence(OSPF_HIT) >= 0.90
    assert hybrid_confidence({"dense_rank": 1, "dense_score": 0.761, "sparse_rank": 3}) >= 0.55  # weakest right answer measured
    assert hybrid_confidence({"dense_rank": 1, "dense_score": 0.596, "sparse_rank": 8}) == 0.0  # off-topic median
    assert hybrid_confidence({"dense_rank": 1, "dense_score": 0.70, "sparse_rank": 1}) == pytest.approx(0.35)


def test_curve_is_monotonic_and_clamped():
    vals = [hybrid_confidence({"dense_score": c / 100, "sparse_rank": 1}) for c in range(40, 100)]
    assert vals == sorted(vals)
    assert vals[0] == 0.0 and vals[-1] == 0.95


def test_dense_only_hit_is_never_high_and_keyword_only_stays_below_the_floor():
    assert hybrid_confidence({"dense_rank": 1, "dense_score": 0.86}) == 0.74
    assert hybrid_confidence({"sparse_rank": 1, "sparse_score": 12.0}) == 0.30
    assert hybrid_confidence({}) == 0.0


def test_unmeasured_dimension_uses_rank_agreement_and_is_never_high():
    assert hybrid_confidence({"dense_rank": 2, "dense_score": 0.5, "sparse_rank": 3}, dense_dim=256) == 0.60
    assert hybrid_confidence({"dense_rank": 2, "dense_score": 0.9}, dense_dim=384) == 0.40


def test_top_confidence_prefers_the_calibrated_value_even_when_zero():
    assert top_confidence([{"confidence_score": 0.0, "score": 0.032}]) == 0.0
    assert top_confidence([{"score": 0.5}, {"confidence_score": 0.9, "score": 0.03}]) == 0.9
    assert top_confidence([], default=0.0) == 0.0


# ------------------------------------------------------------------ searcher
class _Client:
    def collection_exists(self, name):
        return True

    def count(self, collection_name, exact=False):
        return SimpleNamespace(count=10)

    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=768)})))

    def query_points(self, collection_name, query, using, query_filter, limit):
        if using == "dense":
            pts = [("a", 0.86), ("b", 0.80), ("c", 0.65)]
        else:
            pts = [("b", 12.0), ("d", 9.0)]
        return SimpleNamespace(points=[SimpleNamespace(id=i, score=s, payload={"title": i}) for i, s in pts])


class _Sparse:
    def embed(self, texts):
        yield SimpleNamespace(indices=np.array([1]), values=np.array([1.0]))


class _Gemma:
    def __init__(self, mrl_dim=768):
        self.mrl_dim = mrl_dim

    def encode_queries(self, queries, task="search result"):
        return [[0.1] * self.mrl_dim for _ in queries]


def test_searcher_attaches_confidence_without_changing_the_rrf_order(monkeypatch):
    mod = types.ModuleType("scripts.embedding_gemma_onnx")
    mod.EmbeddingGemmaONNX = _Gemma
    monkeypatch.setitem(sys.modules, "scripts.embedding_gemma_onnx", mod)
    s = SovereignSearcher(client=_Client())
    s._sparse_model = _Sparse()
    hits = s.search("how do I check the OSPF neighbor state", limit=5)
    assert [h["id"] for h in hits] == ["b", "a", "d", "c"]  # RRF order: b is in both legs
    assert all(h["score"] == h["rrf_score"] for h in hits)
    conf = {h["id"]: h["confidence_score"] for h in hits}
    assert conf["b"] == hybrid_confidence({"dense_score": 0.80, "sparse_rank": 1})
    assert conf["a"] == 0.74  # dense only: capped below HIGH
    assert conf["d"] == 0.30  # keyword only
    assert conf["c"] == 0.0 + hybrid_confidence({"dense_score": 0.65})


# ------------------------------------------------------------------ NanoRunner
def _chunk(score, conf):
    return {"title": "DSP OSPFPEER", "file_path": "x", "text": "Display OSPF neighbor state.", "score": score, "confidence_score": conf}


def test_nano_runner_uses_the_calibrated_confidence():
    res = NanoRunner().synthesize("how do I check the OSPF neighbor state", [_chunk(0.0318, 0.94)], use_ollama=False, prefer_engine="extractive")
    assert not res.refusal and res.confidence_score == 0.94


def test_nano_runner_does_not_inflate_a_low_calibrated_confidence():
    # 0.02 used to be read as an RRF score and multiplied by 30.5 (0.61), passing the 0.35 floor.
    res = NanoRunner().synthesize("best pizza in naples", [_chunk(0.0318, 0.02)], use_ollama=False, prefer_engine="extractive")
    assert res.refusal and res.confidence_score == 0.02


def test_nano_runner_still_normalises_a_bare_rrf_score():
    res = NanoRunner().synthesize("q", [{"title": "t", "text": "x", "score": 0.0318}], use_ollama=False, prefer_engine="extractive")
    assert res.confidence_score == pytest.approx(min(1.0, 0.0318 * 30.5), abs=1e-3)
