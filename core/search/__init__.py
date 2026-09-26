"""
Hybrid Search Engine for Aegis Sovereign Knowledge Appliance.
Combines FastEmbed ONNX dense vectors with BM25 sparse vectors via Reciprocal Rank Fusion (RRF).
"""

from .searcher import (
    SovereignSearcher,
    reciprocal_rank_fusion,
)

__all__ = [
    "SovereignSearcher",
    "reciprocal_rank_fusion",
]
