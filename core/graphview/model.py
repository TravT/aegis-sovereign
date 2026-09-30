"""Shared shapes of the graph viewer: the node record and the columnar wire format."""

from typing import Any, Dict, List, NamedTuple, Sequence, Tuple


class Node(NamedTuple):
    label: str
    kind: str    # package | topic | ... (per layer)
    group: str   # coarse colour group: the package for the tree
    depth: int
    theme: str   # the filter/colour theme: console family for the tree; "" when unknown


Edge = Tuple[str, str, str]  # source id, target id, kind


def columnar(
    layer: str,
    level: int,
    version: str,
    ids: Sequence[str],
    nodes: Dict[str, Node],
    edges: Sequence[Edge],
    extra: Dict[str, List[Any]],
) -> Dict[str, Any]:
    """The wire format: one array per node attribute, edges as index pairs into the node arrays,
    which keeps ~45k nodes near 1 MB gzipped. ``extra`` adds per-node columns (aligned with ``ids``)."""
    index = {nid: i for i, nid in enumerate(ids)}
    columns: Dict[str, List[Any]] = {
        "id": list(ids),
        "label": [nodes[i].label for i in ids],
        "kind": [nodes[i].kind for i in ids],
        "group": [nodes[i].group for i in ids],
        "depth": [nodes[i].depth for i in ids],
        "theme": [nodes[i].theme for i in ids],
    }
    columns.update(extra)
    return {
        "layer": layer,
        "clearance": level,
        "content_version": version,
        "nodes": columns,
        "edges": {
            "s": [index[s] for s, _, _ in edges],
            "t": [index[t] for _, t, _ in edges],
            "k": [k for _, _, k in edges],
        },
    }
