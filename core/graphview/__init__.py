"""
Graph viewer service (Task 14.1): clearance-aware, level-of-detail slices of the topic tree,
the entity graph and the wiki for the portal's interactive graph. Read-only on the vault.

Not to be confused with ``core.graph`` (GraphRAG entity extraction and the entity store).
"""

from .service import GraphService

__all__ = ["GraphService"]
