"""Deterministic radial layout of the visible topic tree, computed on the server so the browser
does not have to run a force simulation over ~45k nodes.

Leaves are numbered in depth-first order; a node's direction comes from the middle of its leaf
range (an angle in 2D, a point on a Fibonacci sphere in 3D) and its distance from the centre grows
with depth, so a subtree occupies one contiguous sector. Only the caller's visible tree is passed
in, so hidden nodes cannot influence any position.
"""

import math
from typing import Dict, List, Sequence, Tuple

# (x, y, x3, y3, z3)
Position = Tuple[float, float, float, float, float]

CENTER_RADIUS = 20.0   # package roots
RING_GAP = 40.0        # minimum distance between consecutive depth levels
SPACING = 3.0          # minimum distance between neighbours on a ring / sphere
RING_SLACK = 3.5       # rings are sized for 3.5x the nodes they hold (~30% full): uneven crowds then spread locally
GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))


def _spread(values: List[float], gap: float) -> List[float]:
    """The least-squares-closest values to ``values`` (ascending) whose neighbours are >= ``gap``
    apart: pool-adjacent-violators on ``v_i - i*gap``, so a crowded run spreads out symmetrically."""
    blocks: List[List[float]] = []  # [mean, count]
    for i, v in enumerate(values):
        blocks.append([v - i * gap, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            mean2, n2 = blocks.pop()
            mean1, n1 = blocks.pop()
            blocks.append([(mean1 * n1 + mean2 * n2) / (n1 + n2), n1 + n2])
    out: List[float] = []
    for mean, n in blocks:
        out.extend(mean + (len(out) + k) * gap for k in range(n))
    return out


def _spread_cyclic(values: List[float], gap: float, period: float) -> List[float]:
    """``_spread`` for a ring: the seam goes at the ring's largest empty stretch, so a spread-out
    run spills into free space. Results may lie outside [0, period): take them modulo ``period``."""
    n = len(values)
    if n < 2:
        return list(values)
    gaps = [values[(i + 1) % n] - values[i] + (period if i == n - 1 else 0.0) for i in range(n)]
    start = (max(range(n), key=gaps.__getitem__) + 1) % n
    ascending = values[start:] + [v + period for v in values[:start]]
    spread = _spread(ascending, gap)
    out = [0.0] * n
    for k, v in enumerate(spread):
        out[(start + k) % n] = v
    return out


def _min_cyclic_gap(values: List[float], period: float) -> float:
    ordered = sorted(v % period for v in values)
    return min([b - a for a, b in zip(ordered, ordered[1:])] + [ordered[0] + period - ordered[-1]])


def _ring_positions(values: List[float], gap: float, period: float) -> List[float]:
    """Positions on a ring keeping every neighbour >= ``gap`` apart, as close to ``values`` as
    possible: a cyclic spread, or (when the spread crowd would wrap onto the ring's start) the
    smallest blend toward even spacing that works. Even spacing always fits: rings are sized with slack."""
    spread = _spread_cyclic(values, gap, period)
    if len(values) < 2 or _min_cyclic_gap(spread, period) >= gap * (1 - 1e-9):
        return spread
    n = len(values)
    even = [period * (k + 0.5) / n for k in range(n)]
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        blend = [(1 - mid) * v + mid * e for v, e in zip(values, even)]
        if _min_cyclic_gap(blend, period) >= gap:
            hi = mid
        else:
            lo = mid
    return [(1 - hi) * v + hi * e for v, e in zip(values, even)]


def radial_layout(
    depths: Dict[str, int], children: Dict[str, Sequence[str]], roots: Sequence[str]
) -> Dict[str, Position]:
    """Positions for every node reachable from ``roots`` through ``children``."""
    span: Dict[str, Tuple[int, int]] = {}  # node -> [first leaf, end leaf)
    leaves = 0
    stack: List[Tuple[str, bool]] = [(r, False) for r in reversed(list(roots))]
    first: Dict[str, int] = {}
    while stack:
        node, done = stack.pop()
        kids = children.get(node, ())
        if not done:
            first[node] = leaves
            if not kids:
                leaves += 1
                span[node] = (first[node], leaves)
            else:
                stack.append((node, True))
                stack.extend((k, False) for k in reversed(kids))
        else:
            span[node] = (first[node], leaves)
    total = max(leaves, 1)

    by_depth: Dict[int, List[str]] = {}
    for node in sorted(span, key=lambda n: span[n][0]):  # each ring ordered by its leaf ranges
        by_depth.setdefault(depths[node], []).append(node)
    per_depth = {d: len(v) for d, v in by_depth.items()}
    r2: Dict[int, float] = {}
    r3: Dict[int, float] = {}
    for d in range(0, max(per_depth, default=0) + 1):
        n = per_depth.get(d, 0)
        if d == 0:
            r2[d] = r3[d] = CENTER_RADIUS
        else:
            r2[d] = max(r2[d - 1] + RING_GAP, RING_SLACK * n * SPACING / (2 * math.pi))
            r3[d] = max(
                r3[d - 1] + RING_GAP,
                RING_SLACK * n * SPACING / math.sqrt(4 * math.pi * total),
                # points on neighbouring turns of the spiral are ~r*sqrt(4*pi/total) apart, whatever
                # their index distance: keep even that lattice spacing at or above SPACING
                SPACING * math.sqrt(total) / math.sqrt(4 * math.pi),
            )

    # Map every node to its ancestor root for per-package 3D galaxy clustering
    node_to_root: Dict[str, str] = {}
    for r in roots:
        stack = [r]
        while stack:
            curr = stack.pop()
            node_to_root[curr] = r
            stack.extend(children.get(curr, ()))

    root_centers: Dict[str, Tuple[float, float, float]] = {}
    K = len(roots)
    R_sep = 750.0 if K > 1 else 0.0
    for k, r in enumerate(roots):
        if K <= 1:
            root_centers[r] = (0.0, 0.0, 0.0)
        else:
            gz = 1.0 - 2.0 * (k + 0.5) / K
            gr = math.sqrt(max(0.0, 1.0 - gz * gz))
            gtheta = k * GOLDEN_ANGLE
            root_centers[r] = (
                round(R_sep * gr * math.cos(gtheta), 1),
                round(R_sep * gr * math.sin(gtheta), 1),
                round(R_sep * gz, 1),
            )

    out: Dict[str, Position] = {}
    for d, nodes in by_depth.items():
        mids = [(span[n][0] + span[n][1]) / 2.0 for n in nodes]
        # a leaf slice can be far narrower than the spacing the ring can afford: spread the ring out
        u2 = _ring_positions(mids, SPACING * total / (2 * math.pi * r2[d]), total)
        for node, a in zip(nodes, u2):
            angle = 2 * math.pi * a / total
            x2 = round(r2[d] * math.cos(angle), 1)
            y2 = round(r2[d] * math.sin(angle), 1)

            # Volumetric 3D constellation layout per package
            r_pkg = node_to_root.get(node, roots[0] if roots else "")
            gx, gy, gz = root_centers.get(r_pkg, (0.0, 0.0, 0.0))
            if d == 0 or node in roots:
                x3, y3, z3 = gx, gy, gz
            else:
                r_first = span[r_pkg][0] if r_pkg in span else 0
                r_tot = max(1, (span[r_pkg][1] - span[r_pkg][0]) if r_pkg in span else total)
                m_loc = (span[node][0] + span[node][1]) / 2.0 - r_first
                loc_idx = m_loc % r_tot
                z_norm = max(-0.96, min(0.96, 1.0 - 2.0 * (loc_idx + 0.5) / r_tot))
                ring_3d = math.sqrt(max(0.0, 1.0 - z_norm * z_norm))
                theta_3d = loc_idx * GOLDEN_ANGLE

                base_rad = 50.0 + d * 60.0
                h = int(m_loc * 37 + d * 19) % 100
                jitter = 0.88 + 0.24 * (h / 100.0)
                r_eff = base_rad * jitter

                x3 = round(gx + r_eff * ring_3d * math.cos(theta_3d), 1)
                y3 = round(gy + r_eff * ring_3d * math.sin(theta_3d), 1)
                z3 = round(gz + r_eff * z_norm, 1)

            out[node] = (x2, y2, x3, y3, z3)
    return out
