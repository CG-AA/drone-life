"""Worked answer: tower placement as a graph problem (SESSION_PLAN §6.3).

Creeps walk a flow field — Dijkstra from the Keep over the hex grid, where
a 2-high wall costs a ~12-cell detour before chewing through becomes the
cheaper plan (server/app/game/path.py). So a wall does not need to BLOCK a
lane; creeps from one gate already walk single file. It needs to LENGTHEN
the path inside a tower's range: serpentine stubs perpendicular to the
gate→Keep line, alternating sides, spaced two cells apart, all within
16 m of the tower. Every extra cell walked under the gun is another shot.

What a script can see: the wave's gate ("wave N at N .. E .."), the
Keep (0, 0), the game's own suggestion ("build a tower at N .. E ..",
which sits beside the lane 8 cells before the Keep), every tower that
rises ("tower up at N .. E ..") and "hover N m to place". What it cannot
see: the exact lane cells or the tile map — hence stubs on both sides.
Cells are addressed as world points: any point inside a cell places on
that cell, and a repeat hit on the same cell just stacks, which is what a
2-high wall wants (cells are 5.2 m apart centre to centre).

Sixteen tiles is ~6 minutes for one drone: an idea for the wrap, not a bot
that wins alone. Three ferries with the same plan finish inside a wave.
"""

import math
import re
import time

from dronelife import connect, position_in

SITE = re.compile(r"^build a tower at N")
TOWER_UP = re.compile(r"^tower up at N")
WAVE = re.compile(r"^wave \d+ at N")
HOVER = re.compile(r"hover (\d+) m to place")
PITCH = 5.196  # m between hex centres
STUBS = 4  # serpentine stubs, two per side
STUB_LEN = 2  # cells per stub
WALL_HIGH = 2

drone = connect()
quarry: tuple[int, int] | None = None
site: tuple[int, int] | None = None
gate: tuple[int, int] | None = None
tower: tuple[int, int] | None = None
carrying = False
hover_alt: int | None = None
plan: list[tuple[float, float]] = []  # world points to drop tiles on, in order
placed_here = 0


def scan() -> None:
    global quarry, site, gate, tower, carrying, hover_alt, placed_here
    for ev in drone.events():
        if ev.startswith("quarry at"):
            quarry = position_in(ev)
        elif SITE.match(ev):
            site = position_in(ev)
        elif WAVE.match(ev):
            gate = position_in(ev)
        elif TOWER_UP.match(ev):
            tower = position_in(ev)
        elif "got steel" in ev:
            carrying = True
        elif "placed!" in ev or "tower up" in ev or "ring tower" in ev:
            carrying, placed_here = False, placed_here + 1
        elif "steel lost" in ev or "can't build" in ev:
            carrying = False
        m = HOVER.search(ev)
        if m:
            hover_alt = int(m.group(1))


def serpentine(tower_at: tuple[float, float],
               gate_at: tuple[float, float]) -> list[tuple[float, float]]:
    """Stub cells: along the lane direction from the tower, alternating sides."""
    dn, de = -gate_at[0], -gate_at[1]  # gate -> Keep
    norm = math.hypot(dn, de) or 1.0
    along = (dn / norm, de / norm)
    across = (-along[1], along[0])
    pts = []
    for k in range(STUBS):
        side = 1 if k % 2 == 0 else -1
        base_n = tower_at[0] + along[0] * PITCH * (k - STUBS / 2 + 0.5) * 2
        base_e = tower_at[1] + along[1] * PITCH * (k - STUBS / 2 + 0.5) * 2
        for j in range(1, STUB_LEN + 1):
            p = (base_n + across[0] * PITCH * j * side, base_e + across[1] * PITCH * j * side)
            pts += [p] * WALL_HIGH  # two tiles: a wall, not a ramp
    return pts


drone.takeoff(8)
while True:
    scan()
    if not drone.armed:
        drone.takeoff(8)
    if not plan and site and gate:
        plan = [site] * 3 + serpentine(site, gate)  # the tower first, then the maze
        placed_here = 0
        print(f"plan: tower at {site}, {len(plan) - 3} wall tiles after it", flush=True)
    if not carrying and quarry:
        drone.goto(quarry[0], quarry[1], 2)
        deadline = time.time() + 8
        while not carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    elif carrying and plan:
        target = plan[min(placed_here, len(plan) - 1)]
        stacked = sum(1 for p in plan[:placed_here] if p == target)
        drone.goto(target[0], target[1], hover_alt or 4 + 2 * stacked)
        deadline = time.time() + 8
        while carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
        hover_alt = None
        if placed_here >= len(plan):
            plan = []  # done: wait for the next site suggestion
    else:
        time.sleep(0.5)
