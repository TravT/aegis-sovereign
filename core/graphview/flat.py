"""Flat (non-tree) layers: small enough for the browser to lay out itself."""

import sqlite3
from collections import Counter
from typing import Dict, List

from .model import Edge, Node
from .policy import ENTITY_RELATIONS, ENTITY_TYPES


class FlatView:
    """The visible nodes and edges of one flat layer for one clearance level."""

    def __init__(self, nodes: Dict[str, Node], edges: List[Edge]):
        self.nodes = nodes
        self.edges = edges
        degree: Counter = Counter()
        for source, target, _ in edges:
            degree[source] += 1
            degree[target] += 1
        self.degree: Dict[str, int] = {nid: degree[nid] for nid in nodes}


def _marks(values) -> str:
    return ",".join("?" * len(values))


class EntityLayer:
    """Alarms, MML commands, KPIs, features and releases, joined by the Huawei relation kinds."""

    def __init__(self, graph_db: str):
        self._graph_db = graph_db

    def build(self, level: int) -> FlatView:
        con = sqlite3.connect(f"file:{self._graph_db}?mode=ro", uri=True)
        try:
            types = sorted(ENTITY_TYPES)
            rows = con.execute(
                f"SELECT id, name, entity_type FROM entities "
                f"WHERE entity_type IN ({_marks(types)}) AND clearance_level <= ? ORDER BY id",
                (*types, level),
            ).fetchall()
            nodes: Dict[str, Node] = {}
            id_of: Dict[int, str] = {}
            for eid, name, etype in rows:
                nid = f"e:{etype}:{name}"
                id_of[eid] = nid
                nodes[nid] = Node(name, "entity", "entity", 0, etype)
            kinds = sorted(ENTITY_RELATIONS)
            relations = con.execute(
                f"SELECT DISTINCT source_entity_id, target_entity_id, relation_type FROM entity_relations "
                f"WHERE relation_type IN ({_marks(kinds)}) AND clearance_level <= ? "
                f"ORDER BY source_entity_id, target_entity_id, relation_type",
                (*kinds, level),
            ).fetchall()
        finally:
            con.close()
        edges = [(id_of[s], id_of[t], k) for s, t, k in relations if s in id_of and t in id_of]
        return FlatView(nodes, edges)
