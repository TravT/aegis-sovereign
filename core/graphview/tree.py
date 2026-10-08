"""The topic-tree layer: the part of the manual trees one clearance level may see."""

import sqlite3
import threading
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from ..security import ClearanceLevel
from .layout import Position, radial_layout
from .model import Edge, Node

PACKAGE_PREFIX = "pkg:"
TOPIC_PREFIX = "t:"
# a root with no records and nothing beneath it has nothing to derive a level from: fail closed
UNKNOWN_CLEARANCE = int(ClearanceLevel.RESTRICTED)


class TreeView:
    """The visible tree for one clearance level.

    ``nodes`` maps a node id (``pkg:<package>`` or ``t:<topic_id>``) to a Node; ``children`` holds
    visible primary children only; ``edges`` are every visible edge, including second-parent links;
    ``n_desc`` counts visible primary descendants; ``positions`` is the radial layout of this view,
    computed on first use (``meta`` and ``find`` never need it).
    """

    def __init__(self, nodes, children, edges, n_desc, uris: Optional[Dict[str, str]] = None):
        self.nodes: Dict[str, Node] = nodes
        self.children: Dict[str, List[str]] = children
        self.parents: Dict[str, str] = {c: p for p, kids in children.items() for c in kids}
        self.edges: List[Edge] = edges
        self.n_desc: Dict[str, int] = n_desc
        self.uris: Dict[str, str] = uris or {}
        self._positions: Optional[Dict[str, Position]] = None
        self._layout_lock = threading.Lock()

    @property
    def positions(self) -> Dict[str, Position]:
        with self._layout_lock:
            if self._positions is None:
                roots = [n for n, node in self.nodes.items() if node.kind == "package"]
                self._positions = radial_layout({n: node.depth for n, node in self.nodes.items()}, self.children, roots)
            return self._positions

    def expand(self, focus: Optional[str], levels: int) -> List[str]:
        """The entry nodes (every package, or the focus) plus ``levels`` levels of visible children."""
        if focus is None:
            frontier = [n for n, node in self.nodes.items() if node.kind == "package"]
        elif focus in self.nodes:
            frontier = [focus]
        else:
            # hidden and nonexistent nodes must be indistinguishable to the caller
            raise KeyError(f"unknown node {focus}")
        selected = list(frontier)
        for _ in range(max(0, levels)):
            frontier = [c for n in frontier for c in self.children.get(n, ())]
            selected.extend(frontier)
        return selected


class TreeLayer:
    def __init__(self, router_db: str):
        self._router_db = router_db

    def build(self, level: int) -> TreeView:
        con = sqlite3.connect(f"file:{self._router_db}?mode=ro", uri=True)
        try:
            topics = con.execute("SELECT topic_id, package, name, depth FROM topic_nodes").fetchall()
            edges = con.execute("SELECT child, parent, is_primary FROM topic_edges").fetchall()
            own = dict(con.execute(
                "SELECT topic_id, MIN(clearance_level) FROM document_records "
                "WHERE topic_id IS NOT NULL GROUP BY topic_id"
            ))
            consoles = con.execute(
                "SELECT topic_id, console, COUNT(*) FROM document_records "
                "WHERE topic_id IS NOT NULL AND console IS NOT NULL AND console != '' "
                "GROUP BY topic_id, console"
            ).fetchall()
            uri_rows = con.execute("""
                SELECT topic_id,
                       COALESCE(
                           NULLIF(json_extract(metadata, '$.virtual_uri'), ''),
                           NULLIF(json_extract(metadata, '$.file_path'), ''),
                           CASE WHEN doc_identifier LIKE 'archive://%' THEN doc_identifier ELSE '' END,
                           ''
                       ) AS uri
                FROM document_records
                WHERE topic_id IS NOT NULL
            """).fetchall()
        finally:
            con.close()

        topic_uris = {}
        for tid, u in uri_rows:
            if u and tid and (TOPIC_PREFIX + str(tid)) not in topic_uris:
                topic_uris[TOPIC_PREFIX + str(tid)] = u

        clearance = self._derive_clearance(topics, edges, own)
        primary_parent = {c: p for c, p, is_primary in edges if is_primary}
        theme = self._derive_theme(topics, primary_parent, consoles)
        package_of = {tid: package for tid, package, _, _ in topics}

        visible = set()
        for tid, _, _, _ in sorted(topics, key=lambda t: t[3]):  # top-down: parents first
            parent = primary_parent.get(tid)
            if clearance[tid] <= level and (parent is None or parent in visible):
                visible.add(tid)

        nodes: Dict[str, Node] = {}
        children: Dict[str, List[str]] = defaultdict(list)
        out_edges: List[Edge] = []
        roots_by_package: Dict[str, List[str]] = defaultdict(list)
        for tid, package, name, depth in topics:
            if tid in visible:
                nodes[TOPIC_PREFIX + tid] = Node(name, "topic", package, depth, theme[tid])
        for child, parent, is_primary in edges:
            if child not in visible:
                continue
            if parent is None:
                roots_by_package[package_of[child]].append(child)
                out_edges.append((TOPIC_PREFIX + child, PACKAGE_PREFIX + package_of[child], "CHILD_OF"))
            elif parent in visible:
                if is_primary:
                    children[TOPIC_PREFIX + parent].append(TOPIC_PREFIX + child)
                kind = "CHILD_OF" if is_primary else "SECOND_PARENT"
                out_edges.append((TOPIC_PREFIX + child, TOPIC_PREFIX + parent, kind))
        for package in sorted(roots_by_package):
            pid = PACKAGE_PREFIX + package
            nodes[pid] = Node(package, "package", package, 0, "")
            children[pid] = [TOPIC_PREFIX + r for r in roots_by_package[package]]

        # Horizontal sequential reading chain edges between sibling articles under the same parent
        for pid, kids in children.items():
            if len(kids) > 1:
                for i in range(len(kids) - 1):
                    out_edges.append((kids[i], kids[i + 1], "NEXT_TOPIC"))

        n_desc: Dict[str, int] = {}
        for nid in sorted(nodes, key=lambda n: -nodes[n].depth):  # deepest first
            n_desc[nid] = sum(1 + n_desc[c] for c in children.get(nid, ()))
        return TreeView(nodes, dict(children), out_edges, n_desc, uris=topic_uris)

    @staticmethod
    def _derive_clearance(topics, edges, own) -> Dict[str, int]:
        """Minimum over a topic's own records. A topic with none takes the minimum of its primary
        children (a second-parent link is a cross-reference, not containment); a structure-only
        topic with nothing beneath it that has a level inherits its parent's. A root with no
        information at all fails closed."""
        children = defaultdict(list)
        primary_parent: Dict[str, Optional[str]] = {}
        for child, parent, is_primary in edges:
            if is_primary:
                primary_parent[child] = parent
                if parent is not None:
                    children[parent].append(child)

        derived: Dict[str, Optional[int]] = {}
        for tid, _, _, _ in sorted(topics, key=lambda t: -t[3]):  # bottom-up
            if tid in own:
                derived[tid] = own[tid]
            else:
                known = [derived[c] for c in children[tid] if derived[c] is not None]
                derived[tid] = min(known) if known else None

        effective: Dict[str, int] = {}
        for tid, _, _, _ in sorted(topics, key=lambda t: t[3]):  # top-down
            if derived[tid] is not None:
                effective[tid] = derived[tid]
            else:
                parent = primary_parent.get(tid)
                effective[tid] = effective[parent] if parent is not None else UNKNOWN_CLEARANCE
        return effective

    @staticmethod
    def _derive_theme(topics, primary_parent, consoles) -> Dict[str, str]:
        """The most common console among a topic's records (ties: alphabetical); a topic with none
        inherits its parent's theme, so a whole chapter is coloured coherently."""
        counts: Dict[str, Counter] = defaultdict(Counter)
        for tid, console, n in consoles:
            counts[tid][console] += n
        theme: Dict[str, str] = {}
        for tid, _, _, _ in sorted(topics, key=lambda t: t[3]):  # top-down
            if counts[tid]:
                theme[tid] = min(counts[tid], key=lambda c: (-counts[tid][c], c))
            else:
                parent = primary_parent.get(tid)
                theme[tid] = theme[parent] if parent is not None else ""
        return theme
