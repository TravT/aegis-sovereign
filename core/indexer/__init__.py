"""
Aegis Sovereign Indexer Package
Dual-vector indexing (Dense BAAI/bge-small-en-v1.5 + Sparse BM25) into Qdrant.
Supports both Client-Server Qdrant and In-Process Serverless Embedded Qdrant.
"""

from .dual_encoder import SovereignIndexer, DEFAULT_COLLECTION, DEFAULT_DENSE_MODEL, DEFAULT_SPARSE_MODEL

__all__ = ["SovereignIndexer", "DEFAULT_COLLECTION", "DEFAULT_DENSE_MODEL", "DEFAULT_SPARSE_MODEL"]
