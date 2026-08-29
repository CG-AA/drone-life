"""Worked answer: predict quests — model a creep's march and park where it
will be.

    quest 7: runner at N 40 E -12, in 15 s?

The answer is a place: where THAT creep stands T seconds after the line.
Creeps walk cell-centre to cell-centre on the hex grid toward the Keep at
(0, 0), at `min(2.5, 1.5 + 0.1 * (wave - 1))` m/s times the kind's
multiplier (runner 1.5, brute 0.65, grunt/sapper 1.0; a buffed wave 1.2 x
more). On an empty map many hex paths tie, and the creep follows exactly the
one the server's flood field picks — so this script ports that field
(server/app/game/path.py: a heap ordered by (cost, q, r), neighbours in
DIRECTIONS order, a parent replaced only by a strictly cheaper one) and the
walker (server/app/game/units.py) over the hex math (server/app/game/hex.py).
The game only issues creeps whose real path equals the empty-map one, so a
faithful port is the whole answer. Then: be within 6 m, and STILL for the
last 2 s — a drone still chasing the callouts does not count.
"""

import heapq
import math
import re
import time

from dronelife import connect

QUEST = re.compile(r"^quest (\d+): (\w+) at N (-?\d+) E (-?\d+), in (\d+) s\?$")
WAVE = re.compile(r"^wave (\d+) at N")
BUFF = re.compile(r"^wave (\d+) buffed: faster")

HEX = 3.0  # HEX_SIZE
SQRT3 = math.sqrt(3.0)
DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
LIMIT = 100.0 - HEX  # in_bounds: the whole hex inside the arena
SPEED_MULT = {"grunt": 1.0, "runner": 1.5, "brute": 0.65, "sapper": 1.0, "champion": 0.6}
PARK_ALT = 6.0


def axial_to_world(cell):
    q, r = cell
    return HEX * 1.5 * r, HEX * SQRT3 * (q + r / 2.0)


def world_to_axial(n, e):
    rf = (2.0 / 3.0) * n / HEX
    qf = (SQRT3 / 3.0) * e / HEX - rf / 2.0
    x, z = qf, rf
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy <= dz:
        rz = -rx - ry
    return int(rx), int(rz)


def in_bounds(cell):
    n, e = axial_to_world(cell)
    return abs(n) <= LIMIT and abs(e) <= LIMIT


def flood(goal=(0, 0)):
    """path.flood on an empty map: every edge costs 1, the tie-break is the law."""
    cost = {goal: 0.0}
    next_step = {}
    heap = [(0.0, goal[0], goal[1])]
    while heap:
        c, q, r = heapq.heappop(heap)
        if c > cost[(q, r)]:
            continue
        for dq, dr in DIRECTIONS:
            nb = (q + dq, r + dr)
            if not in_bounds(nb):
                continue
            if c + 1.0 < cost.get(nb, math.inf):
                cost[nb] = c + 1.0
                next_step[nb] = (q, r)
                heapq.heappush(heap, (c + 1.0, nb[0], nb[1]))
    return next_step


FIELD = flood()


def march(n, e, speed, seconds, dt=0.1):
    """units.step_units for a walker on flat ground: head for the next cell's
    centre, snap to it when a step would overshoot."""
    for _ in range(round(seconds / dt)):
        here = world_to_axial(n, e)
        nxt = FIELD.get(here)
        if nxt is None:
            break  # at the Keep
        tn, te = axial_to_world(nxt)
        dn, de = tn - n, te - e
        dist = math.hypot(dn, de)
        step = speed * dt
        if dist <= step:
            n, e = tn, te
        else:
            n, e = n + dn / dist * step, e + de / dist * step
    return n, e


drone = connect()
drone.say("quest")
drone.takeoff(PARK_ALT)
# park over the Keep between quests: every creep walks toward it, so every
# answer is close — from the pad the far gates are out of reach in 8 s
drone.goto(0, 0, PARK_ALT, wait=False)
wave, buffed = 1, False
while True:
    if not drone.armed:
        drone.takeoff(PARK_ALT)
        drone.goto(0, 0, PARK_ALT, wait=False)
    for ev in drone.events():
        m = WAVE.match(ev)
        if m:
            wave, buffed = int(m.group(1)), False
            continue
        if BUFF.match(ev):
            buffed = True
            continue
        m = QUEST.match(ev)
        if not m:
            continue
        _qid, kind, n, e, seconds = m.groups()
        base = min(2.5, 1.5 + 0.1 * (wave - 1)) * (1.2 if buffed else 1.0)
        speed = base * SPEED_MULT.get(kind, 1.0)
        tn, te = march(float(n), float(e), speed, float(seconds))
        print(f"{kind} at ({n}, {e}) -> ({tn:.1f}, {te:.1f}) in {seconds} s", flush=True)
        # get there and hold: the check wants 2 s of stillness before T. No
        # blocking goto — a target out of reach must not end the script
        drone.goto(tn, te, PARK_ALT, wait=False)
        drone.wait(float(seconds) + 0.5)  # hover through the check
        drone.goto(0, 0, PARK_ALT, wait=False)
    time.sleep(0.2)
