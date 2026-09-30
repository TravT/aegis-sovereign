"""GraphService: the single interface of the graph viewer module (slice / find, meta to follow)."""

import hashlib
import os
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Union

from ..security import ClearanceLevel
from .crosslinks import alarm_topics, is_alarm_id
from .flat import EntityLayer, FlatView
from .model import columnar
from .tree import TreeLayer, TreeView
from .wiki import WikiLayer

Clearance = Union[str, int, ClearanceLevel]

DEFAULT_LEVELS = 2

LAYER_LABELS = {"tree": "Manual trees", "entity": "Alarms, MML commands and KPIs", "wiki": "Homelab wiki"}
# relationships that are part of the contract but not extracted yet (Task 14.3): alarm -> alarm
# causes and the order of MML steps in a runbook (ALM -> MML -> MML)
RESERVED_EDGE_KINDS = ["CAUSED_BY", "NEXT_STEP"]


class GraphService:
    def __init__(self, router_db: str, graph_db: str, wiki_dir: Optional[str] = None):
        self._router_db = router_db
        self._graph_db = graph_db
        self._wiki = WikiLayer(wiki_dir) if wiki_dir else None
        self._layers: Dict[str, Any] = {"tree": TreeLayer(router_db), "entity": EntityLayer(graph_db)}
        if self._wiki:
            self._layers["wiki"] = self._wiki
        self._lock = threading.RLock()  # re-entrant: building a cached entry may need another
        self._cached_version: Optional[str] = None
        self._views: Dict[Tuple[str, int], Any] = {}

    def content_version(self) -> str:
        """Changes whenever either vault database is written (size and mtime of each db and its WAL)
        or a wiki note is added, removed or edited."""
        parts = [self._wiki.signature() if self._wiki else "-"]
        for path in (self._router_db, self._graph_db):
            for suffix in ("", "-wal"):
                try:
                    st = os.stat(path + suffix)
                    parts.append(f"{st.st_mtime_ns}:{st.st_size}")
                except OSError:
                    parts.append("-")
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]

    def meta(self, clearance: Clearance) -> Dict[str, Any]:
        """What the caller can open: the layers with their sizes after clearance, the theme legend
        (most common first) and the edge kinds actually present, plus the kinds reserved for later."""
        level = int(ClearanceLevel.from_string(clearance))
        version = self.content_version()
        layers = []
        for layer in self._layers:
            view = self._view(layer, level, version)
            themes = Counter(node.theme for node in view.nodes.values() if node.theme)
            layers.append({
                "id": layer,
                "label": LAYER_LABELS[layer],
                "nodes": len(view.nodes),
                "edges": len(view.edges),
                "edge_kinds": dict(Counter(kind for _, _, kind in view.edges)),
                "themes": [{"theme": t, "count": n} for t, n in sorted(themes.items(), key=lambda i: (-i[1], i[0]))],
            })
        return {
            "clearance": level,
            "content_version": version,
            "layers": layers,
            "reserved_edge_kinds": list(RESERVED_EDGE_KINDS),
        }

    def slice(
        self,
        layer: str,
        clearance: Clearance,
        focus: Optional[str] = None,
        mode: str = "clustered",
        levels: int = DEFAULT_LEVELS,
    ) -> Dict[str, Any]:
        """Nodes and edges of a layer that the caller's clearance allows, in the columnar wire format.

        The tree layer is level-of-detail: ``clustered`` returns the package roots plus ``levels``
        levels (or ``focus`` plus ``levels`` levels below it), ``all`` returns every visible node.
        Flat layers (entity, wiki) are always returned whole."""
        level = int(ClearanceLevel.from_string(clearance))
        version = self.content_version()
        view = self._view(layer, level, version)
        if isinstance(view, FlatView):
            return self._flat_slice(layer, view, level, version)
        if mode == "all":
            selected = list(view.nodes)
        elif mode == "clustered":
            selected = view.expand(focus, levels)
        else:
            raise ValueError(f"unknown mode {mode!r}")
        return self._tree_slice(view, level, version, selected, complete=(mode == "all"))

    def find(
        self, text: str, clearance: Clearance, layer: str = "tree", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Visible nodes whose label contains ``text`` (exact matches first, then prefix, then
        contains; shallower first), each with its ancestor path so the viewer can reveal it."""
        level = int(ClearanceLevel.from_string(clearance))
        view = self._view(layer, level, self.content_version())
        needle = text.strip().lower()
        if not needle:
            return []
        ranked = []
        for nid, node in view.nodes.items():
            low = node.label.lower()
            if needle in low:
                rank = 0 if low == needle else 1 if low.startswith(needle) else 2
                ranked.append((rank, node.depth, low, nid))
        ranked.sort()
        parents = view.parents if isinstance(view, TreeView) else {}
        hits = []
        for _, _, _, nid in ranked[: max(0, limit)]:
            path = [nid]
            while path[-1] in parents:
                path.append(parents[path[-1]])
            node = view.nodes[nid]
            hits.append({"id": nid, "label": node.label, "layer": layer, "kind": node.kind, "path": path[::-1]})
        return hits

    # ---- views ------------------------------------------------------------------------------

    def _view(self, layer: str, level: int, version: str) -> Union[TreeView, FlatView]:
        """The visible part of a layer for a clearance level, cached until the vault changes."""
        if layer not in self._layers:
            raise ValueError(f"unknown layer {layer!r}")
        return self._cached((layer, level), version, lambda: self._layers[layer].build(level))

    def _cached(self, key: Tuple[str, int], version: str, build) -> Any:
        with self._lock:
            if version != self._cached_version:
                self._cached_version, self._views = version, {}
            if key not in self._views:
                self._views[key] = build()
            return self._views[key]

    @staticmethod
    def _tree_slice(view: TreeView, level: int, version: str, selected: List[str], complete: bool) -> Dict[str, Any]:
        chosen = set(selected)
        edges = [e for e in view.edges if e[0] in chosen and e[1] in chosen]
        pos = [view.positions[n] for n in selected]
        extra = {
            "n_desc": [view.n_desc[n] for n in selected],
            "expandable": [
                0 if complete else int(any(c not in chosen for c in view.children.get(n, ())))
                for n in selected
            ],
            "x": [p[0] for p in pos],
            "y": [p[1] for p in pos],
            "x3": [p[2] for p in pos],
            "y3": [p[3] for p in pos],
            "z3": [p[4] for p in pos],
        }
        return columnar("tree", level, version, selected, view.nodes, edges, extra)

    def _flat_slice(self, layer: str, view: FlatView, level: int, version: str) -> Dict[str, Any]:
        ids = list(view.nodes)
        extra: Dict[str, List[Any]] = {"degree": [view.degree[n] for n in ids]}
        if layer == "entity":
            topics = self._cached(
                ("alarm_topics", level), version,
                lambda: alarm_topics(self._view("tree", level, version)),
            )
            extra["see_also"] = [
                topics.get(view.nodes[n].label, []) if is_alarm_id(view.nodes[n].label) else []
                for n in ids
            ]
        return columnar(layer, level, version, ids, view.nodes, view.edges, extra)
