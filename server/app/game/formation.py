"""Formations: three drones holding a triangle over a point.

Pure geometry over DroneView snapshots, for siege's sealed south gate: the
gate opens only while three pilots keep a triangle above it — the puzzle
pays the whole room (the lane's kills go to the pot), never the trio.
Deterministic: candidates sorted by id, first valid triple wins.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import combinations

from ..sim.backend import DroneView


def _angles(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """The smallest interior angle of triangle abc, in degrees."""
    def ang(p, q, r):
        v1 = (q[0] - p[0], q[1] - p[1])
        v2 = (r[0] - p[0], r[1] - p[1])
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-9 or n2 < 1e-9:
            return 0.0
        return math.degrees(math.acos(max(-1.0, min(1.0, dot / (n1 * n2)))))
    return min(ang(a, b, c), ang(b, a, c), ang(c, a, b))


def triangle(drones: Iterable[DroneView], n: float, e: float, radius: float,
             min_d: float, max_d: float, min_angle: float = 30.0,
             ) -> tuple[DroneView, DroneView, DroneView] | None:
    """Three armed, airborne drones within `radius` of (n, e), pairwise
    between `min_d` and `max_d` apart, not in a line (every corner at least
    `min_angle`). The nearest eight are considered; None if no triple fits."""
    near = sorted(
        (d for d in drones
         if d.armed and not d.crashed and not d.on_ground
         and math.hypot(d.n - n, d.e - e) <= radius),
        key=lambda d: (math.hypot(d.n - n, d.e - e), d.id))[:8]
    for a, b, c in combinations(sorted(near, key=lambda d: d.id), 3):
        pts = [(a.n, a.e), (b.n, b.e), (c.n, c.e)]
        sides = [math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in combinations(pts, 2)]
        if all(min_d <= s <= max_d for s in sides) and _angles(*pts) >= min_angle:
            return a, b, c
    return None
