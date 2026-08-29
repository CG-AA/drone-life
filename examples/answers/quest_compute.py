"""Worked answer: compute quests — the answer is an altitude over the Keep.

    quest 7: alt = dist to N 40 E -12 / 4     Euclid from the Keep (0, 0)
    quest 7: alt = dist pad to N 40 E -12 / 4 …from YOUR pad (position() before takeoff)
    quest 7: alt = hexes to N 40 E -12        hex steps from the Keep
    quest 7: alt = hexes pad to N 40 E -12    …from your pad
    quest 7: alt = gates x 10 + wave          count the "wave N at" + "also at" lines
    quest 7: alt = creeps this wave           add up the counts in those lines

Hover over the Keep (within 3 m) at the answer (±1 m) for 2 s. Hex distance
needs the grid: cells are (q, r), n = 4.5 r, e = 5.196 (q + r/2), and the
distance between two cells is (|dq| + |dr| + |dq + dr|) / 2
(server/app/game/hex.py). Positions in the text are cell centres, so
rounding them back to a cell is exact.
"""

import math
import re
import time

from dronelife import connect

QUEST = re.compile(
    r"^(?:room )?quest (\d+): alt = (dist|hexes)( pad)? to N (-?\d+) E (-?\d+)(?: / (\d+))?$")
GATES = re.compile(r"^(?:room )?quest (\d+): alt = gates x 10 \+ wave$")
CREEPS = re.compile(r"^(?:room )?quest (\d+): alt = creeps this wave$")
WAVE = re.compile(r"^wave (\d+) (at|also at) N -?\d+ E -?\d+, (\d+) creeps")

HEX = 3.0
SQRT3 = math.sqrt(3.0)


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


def hex_distance(a, b):
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


drone = connect()
while drone.position() == (0.0, 0.0, 0.0):  # connect() waits for the first fix; be sure
    time.sleep(0.05)
pad = drone.position()[:2]  # where I sit before takeoff: my pad
drone.say("quest")
drone.takeoff(6)
wave, gates, creeps = 0, 0, 0
while True:
    if not drone.armed:
        drone.takeoff(6)
    for ev in drone.events():
        m = WAVE.match(ev)
        if m:
            w, which, count = int(m.group(1)), m.group(2), int(m.group(3))
            if w != wave or which == "at":
                wave, gates, creeps = w, 0, 0
            gates += 1
            creeps += count
            continue
        answer = None
        m = QUEST.match(ev)
        if m:
            _qid, how, from_pad, n, e, k = m.groups()
            origin = pad if from_pad else (0.0, 0.0)
            target = (float(n), float(e))
            if how == "dist":
                answer = math.hypot(target[0] - origin[0], target[1] - origin[1]) / int(k)
            else:
                answer = float(hex_distance(world_to_axial(*origin), world_to_axial(*target)))
        elif GATES.match(ev):
            answer = gates * 10 + wave
        elif CREEPS.match(ev):
            answer = float(creeps)
        if answer is None:
            continue
        print(f"{ev!r} -> hover at {answer:.2f} m", flush=True)
        drone.goto(0, 0, answer, tolerance=0.5, timeout=40)
        drone.wait(3)  # the check wants 2 s inside ±1 m
    time.sleep(0.2)
