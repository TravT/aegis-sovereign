"""Calibrated confidence for hybrid (dense + BM25) hits (findings register U8).

The RRF score (k=60) is rank-based: about 0.033 for the first hit whatever the query, so it said nothing about
whether the answer is right, and the portal showed "LOW_UNVERIFIED (0.03)" on correct answers. The top dense
cosine does separate them. Measured on 13 Oct 2026 over `sovereign_chunks` (EmbeddingGemma 768-d), see
`benchmarks/u8_confidence_calibration/`: engineer-worded questions whose right command was in the top 5 had a
best cosine of 0.761 to 0.863 (77 queries); questions the manuals cannot answer had 0.547 to 0.762 (median 0.596,
28 of 30 below 0.70). The curve puts the 0.35 refusal floor at cosine 0.70.
"""

from typing import Any, Dict, Iterable, Optional

# (cosine, confidence) knots for EmbeddingGemma 768-d; linear in between, clamped at both ends.
GEMMA_768_KNOTS = ((0.60, 0.0), (0.70, 0.35), (0.78, 0.75), (0.86, 0.95))
# Without a BM25 match in the fused pool the dense leg alone cannot reach HIGH (>= 0.75).
NO_LEXICAL_CAP = 0.74
# A keyword-only hit (no dense score) stays below the refusal floor on its own.
KEYWORD_ONLY = 0.30


def _interp(x: float, knots) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    return knots[-1][1]


def hybrid_confidence(meta: Dict[str, Any], dense_dim: int = 768) -> float:
    """Confidence in [0, 1] for one fused hit, from its dense cosine and whether BM25 also found it."""
    dense_score = meta.get("dense_score")
    has_lexical = meta.get("sparse_rank") is not None
    if dense_score is None:
        return KEYWORD_ONLY if has_lexical else 0.0
    if dense_dim == 768:
        conf = _interp(float(dense_score), GEMMA_768_KNOTS)
    else:
        # Not measured for 256-d / 384-d models: rank agreement only, never HIGH.
        both = has_lexical and (meta.get("dense_rank") or 99) <= 10 and (meta.get("sparse_rank") or 99) <= 10
        conf = 0.60 if both else 0.40
    if not has_lexical:
        conf = min(conf, NO_LEXICAL_CAP)
    return round(conf, 4)


def top_confidence(results: Iterable[Dict[str, Any]], default: float = 0.0) -> float:
    """Highest per-hit confidence; a hit's own `confidence_score` wins over its raw `score`, even when 0."""
    best: Optional[float] = None
    for r in results:
        sc = r.get("confidence_score")
        if sc is None:
            sc = r.get("score")
        if sc is None:
            continue
        best = float(sc) if best is None else max(best, float(sc))
    return default if best is None else best
