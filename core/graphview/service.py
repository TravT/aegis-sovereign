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
MODES = ('clustered', 'all')
MAX_FIND = 200  # hard cap on find results, whatever limit the caller asks for

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
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        version = self.content_version()
        view = self._view(layer, level, version)
        if isinstance(view, FlatView):
            return self._flat_slice(layer, view, level, version)
        if mode == "all":
            selected = list(view.nodes)
        else:
            selected = view.expand(focus, levels)
        return self._tree_slice(view, level, version, selected, complete=(mode == "all"))

    def find(
        self, text: str, clearance: Clearance, layer: str = "tree", limit: int = 50,
        node_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Visible nodes whose label contains ``text`` (exact matches first, then prefix, then
        contains; shallower first), each with its ancestor path so the viewer can reveal it.
        With ``node_id`` it returns just that node (if the caller may see it)."""
        level = int(ClearanceLevel.from_string(clearance))
        view = self._view(layer, level, self.content_version())
        if node_id is not None:
            return [self._hit(view, node_id, layer)] if node_id in view.nodes else []
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
        return [self._hit(view, nid, layer) for _, _, _, nid in ranked[: max(0, min(limit, MAX_FIND))]]

    @staticmethod
    def _hit(view: Union[TreeView, FlatView], nid: str, layer: str) -> Dict[str, Any]:
        parents = view.parents if isinstance(view, TreeView) else {}
        path = [nid]
        while path[-1] in parents:
            path.append(parents[path[-1]])
        node = view.nodes[nid]
        return {"id": nid, "label": node.label, "layer": layer, "kind": node.kind, "path": path[::-1]}

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

    def ego_subgraph(
        self,
        target: str,
        clearance: Clearance = "restricted",
        depth: int = 2,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Returns the local ego-subgraph centered around target (URI, identifier, or node ID),
        connecting tree topics, entities, and wiki notes up to limit nodes."""
        level = int(ClearanceLevel.from_string(clearance))
        version = self.content_version()

        target_str = (target or "").strip()
        if not target_str:
            return {"center": None, "nodes": [], "edges": []}

        wv = self._view("wiki", level, version) if self._wiki else None
        ev = self._view("entity", level, version)
        tv = self._view("tree", level, version)

        center_id = None
        center_layer = None
        center_node = None

        # 1. Resolve Center Node
        # A) Check Wiki
        if wv:
            clean_target = target_str.replace("archive://", "")
            if "/docs/wiki/" in clean_target:
                rel = clean_target.split("/docs/wiki/")[-1]
                w_id = f"w:{rel}"
                if w_id in wv.nodes:
                    center_id, center_layer, center_node = w_id, "wiki", wv.nodes[w_id]
            if not center_id:
                for nid, node in wv.nodes.items():
                    if target_str in nid or target_str.lower() in node.label.lower():
                        center_id, center_layer, center_node = nid, "wiki", node
                        break

        # B) Check Entity
        if not center_id and ev:
            for nid, node in ev.nodes.items():
                lbl_low = node.label.lower()
                tgt_low = target_str.lower()
                if lbl_low == tgt_low or tgt_low in nid.lower() or (len(tgt_low) > 4 and tgt_low in lbl_low):
                    center_id, center_layer, center_node = nid, "entity", node
                    break

        # C) Check Tree
        if not center_id and tv:
            clean_t = target_str
            if "#resources/" in clean_t:
                try:
                    import sqlite3
                    con = sqlite3.connect(f"file:{self._router_db}?mode=ro", uri=True)
                    row = con.execute(
                        "SELECT topic_id, title FROM document_records WHERE doc_identifier = ? OR metadata LIKE ? LIMIT 1",
                        (target_str, f"%{target_str}%"),
                    ).fetchone()
                    con.close()
                    if row and row[0]:
                        tid = f"t:{row[0]}"
                        if tid in tv.nodes:
                            center_id, center_layer, center_node = tid, "tree", tv.nodes[tid]
                except Exception:
                    pass
            if not center_id:
                for nid, node in tv.nodes.items():
                    if target_str.lower() in node.label.lower() or target_str in nid:
                        center_id, center_layer, center_node = nid, "tree", node
                        break

        if not center_id:
            return {"center": None, "nodes": [], "edges": []}

        # 2. Collect 1-hop and 2-hop Neighbors
        chosen_nodes = {center_id: (center_layer, center_node)}
        chosen_edges = []
        frontier = {center_id}

        for _ in range(max(1, depth)):
            next_frontier = set()
            for curr in frontier:
                curr_layer = chosen_nodes[curr][0]

                if curr_layer == "wiki" and wv:
                    for s, t, k in wv.edges:
                        if s == curr and t in wv.nodes and t not in chosen_nodes and len(chosen_nodes) < limit:
                            chosen_nodes[t] = ("wiki", wv.nodes[t])
                            chosen_edges.append({"source": s, "target": t, "kind": k})
                            next_frontier.add(t)
                        elif t == curr and s in wv.nodes and s not in chosen_nodes and len(chosen_nodes) < limit:
                            chosen_nodes[s] = ("wiki", wv.nodes[s])
                            chosen_edges.append({"source": s, "target": t, "kind": k})
                            next_frontier.add(s)

                elif curr_layer == "entity" and ev:
                    for s, t, k in ev.edges:
                        if s == curr and t in ev.nodes and t not in chosen_nodes and len(chosen_nodes) < limit:
                            chosen_nodes[t] = ("entity", ev.nodes[t])
                            chosen_edges.append({"source": s, "target": t, "kind": k})
                            next_frontier.add(t)
                        elif t == curr and s in ev.nodes and s not in chosen_nodes and len(chosen_nodes) < limit:
                            chosen_nodes[s] = ("entity", ev.nodes[s])
                            chosen_edges.append({"source": s, "target": t, "kind": k})
                            next_frontier.add(s)

                elif curr_layer == "tree" and tv:
                    p = tv.parents.get(curr)
                    if p and p in tv.nodes and p not in chosen_nodes and len(chosen_nodes) < limit:
                        chosen_nodes[p] = ("tree", tv.nodes[p])
                        chosen_edges.append({"source": curr, "target": p, "kind": "CHILD_OF"})
                        next_frontier.add(p)
                    for c in tv.children.get(curr, ())[:10]:
                        if c in tv.nodes and c not in chosen_nodes and len(chosen_nodes) < limit:
                            chosen_nodes[c] = ("tree", tv.nodes[c])
                            chosen_edges.append({"source": c, "target": curr, "kind": "CHILD_OF"})
                            next_frontier.add(c)
                    if p:
                        for sib in tv.children.get(p, ())[:10]:
                            if sib != curr and sib in tv.nodes and sib not in chosen_nodes and len(chosen_nodes) < limit:
                                chosen_nodes[sib] = ("tree", tv.nodes[sib])
                                chosen_edges.append({"source": sib, "target": p, "kind": "CHILD_OF"})
                                next_frontier.add(sib)

                # Cross-layer links
                if curr_layer == "entity" and tv:
                    lbl = chosen_nodes[curr][1].label.split("(")[0].strip()
                    if is_alarm_id(lbl):
                        topics = self._cached(("alarm_topics", level), version, lambda: alarm_topics(tv))
                        for t_lbl in topics.get(lbl, ())[:5]:
                            for t_id, t_node in tv.nodes.items():
                                if t_node.label == t_lbl and t_id not in chosen_nodes and len(chosen_nodes) < limit:
                                    chosen_nodes[t_id] = ("tree", t_node)
                                    chosen_edges.append({"source": curr, "target": t_id, "kind": "CANONICAL_TOPIC"})
                                    next_frontier.add(t_id)
                                    break

                if curr_layer == "wiki" and ev:
                    w_title = chosen_nodes[curr][1].label
                    for e_id, e_node in ev.nodes.items():
                        if len(chosen_nodes) >= limit:
                            break
                        if (len(e_node.label) > 4 and e_node.label in w_title) or (len(e_node.label) > 5 and e_node.label in curr):
                            if e_id not in chosen_nodes:
                                chosen_nodes[e_id] = ("entity", e_node)
                                chosen_edges.append({"source": curr, "target": e_id, "kind": "MENTIONS_ENTITY"})
                                next_frontier.add(e_id)

            frontier = next_frontier
            if len(chosen_nodes) >= limit:
                break

        def node_uri(nid: str, lyr: str) -> str:
            if lyr == "wiki":
                rel = nid[2:] if nid.startswith("w:") else nid
                return f"archive:///home/tlima/Enterprise_Hub/docs/wiki/{rel}"
            elif lyr == "tree":
                return f"tree://{nid}"
            elif lyr == "entity":
                return f"entity://{nid}"
            return nid

        result_nodes = [
            {
                "id": nid,
                "label": n_obj.label,
                "kind": n_obj.kind,
                "layer": lyr,
                "theme": getattr(n_obj, "theme", ""),
                "uri": node_uri(nid, lyr),
                "is_center": (nid == center_id),
            }
            for nid, (lyr, n_obj) in chosen_nodes.items()
        ]

        return {
            "target": target_str,
            "center": {
                "id": center_id,
                "label": center_node.label,
                "kind": center_node.kind,
                "layer": center_layer,
                "theme": getattr(center_node, "theme", ""),
                "uri": node_uri(center_id, center_layer),
            },
            "nodes": result_nodes,
            "edges": chosen_edges,
        }
