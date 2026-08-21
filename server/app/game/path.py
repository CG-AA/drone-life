"""Flow fields for ground units: chew-aware Dijkstra over the hex grid.

One flood from the goal covers every in-bounds cell, so a unit ALWAYS has a
next step — walls are expensive detours, never dead ends. The edge cost is
    1 + chew_cost * max(0, |height difference| - climb)
so a climbable step costs 1 like open ground, and each tile beyond the unit's
climb prices in the time to chew it down. Full enclosure therefore routes
creeps to the cheapest breach instead of stalling them at the walls (the hole
a plain BFS + "chew when no path" scheme falls into).

Recompute on TileMap.version change only; the arena is ~1500 cells.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from . import hex
from .hex import Axial
from .tiles import TileMap

# Extra cost per tile of over-climb. Crossing a 2-high wall at climb=1 costs
# 2 expensive edges (up, down) = +12 over open ground, so walls reroute creeps
# up to a ~12-cell detour before chewing through becomes the cheaper plan.
CHEW_COST = 6.0


@dataclass(frozen=True)
class FlowField:
    goal: Axial
    climb: int
    next_step: dict[Axial, Axial]  # cell -> the neighbor one step closer
    cost: dict[Axial, float]

    def has(self, cell: Axial) -> bool:
        return cell in self.cost

    def toward(self, cell: Axial) -> Axial | None:
        """The next cell on the cheapest path to the goal; None at the goal
        (or off the field entirely)."""
        return self.next_step.get(cell)


def flood(tm: TileMap, goal: Axial, climb: int = 0,
          chew_cost: float = CHEW_COST) -> FlowField:
    """Dijkstra outward from `goal`. Deterministic: the heap breaks cost ties
    on (q, r), neighbors relax in DIRECTIONS order, and a parent is only
    replaced by a strictly cheaper one."""
    cost: dict[Axial, float] = {goal: 0.0}
    next_step: dict[Axial, Axial] = {}
    heap: list[tuple[float, int, int]] = [(0.0, goal[0], goal[1])]
    while heap:
        here_cost, q, r = heapq.heappop(heap)
        cell = (q, r)
        if here_cost > cost[cell]:
            continue  # stale entry, already relaxed cheaper
        here_h = tm.height(cell)
        for nb in hex.neighbors(cell):
            if not tm.in_bounds(nb):
                continue
            step = 1.0 + chew_cost * max(0, abs(tm.height(nb) - here_h) - climb)
            nb_cost = here_cost + step
            if nb_cost < cost.get(nb, float("inf")):
                cost[nb] = nb_cost
                next_step[nb] = cell
                heapq.heappush(heap, (nb_cost, nb[0], nb[1]))
    return FlowField(goal, climb, next_step, cost)
