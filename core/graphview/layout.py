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

    out: Dict[str, Position] = {}
    for d, nodes in by_depth.items():
        mids = [(span[n][0] + span[n][1]) / 2.0 for n in nodes]
        # a leaf slice can be far narrower than the spacing the ring can afford: spread the ring out
        u2 = _ring_positions(mids, SPACING * total / (2 * math.pi * r2[d]), total)
        u3 = _ring_positions(mids, SPACING * math.sqrt(total) / (r3[d] * math.sqrt(4 * math.pi)), total)
        for node, a, b in zip(nodes, u2, u3):
            b %= total
            angle = 2 * math.pi * a / total
            z = max(-1.0, min(1.0, 1.0 - 2.0 * b / total))
            ring = math.sqrt(1.0 - z * z)
            theta = b * GOLDEN_ANGLE
            out[node] = (
                round(r2[d] * math.cos(angle), 1),
                round(r2[d] * math.sin(angle), 1),
                round(r3[d] * ring * math.cos(theta), 1),
                round(r3[d] * ring * math.sin(theta), 1),
                round(r3[d] * z, 1),
            )
    return out
