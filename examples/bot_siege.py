"""Demo bot: hunts creeps in the siege game by chasing GAME: messages.

Zap loop: the game calls out your nearest creep every few seconds. The
announcement is where the creep WAS — but creeps always march toward the
Keep at (0, 0), so aim a few meters ahead along that line and hover low;
the creep walks into your zap circle. Retarget on every fresh call.
"""

import math
import re
import time

from dronelife import connect

CREEP = re.compile(r"creep at N (-?\d+) E (-?\d+)")
LEAD = 6.0  # m ahead of the announcement, along the creep's march
CRUISE = 9  # m: above every wall (8 m) while crossing the map

drone = connect()
target: tuple[int, int] | None = None


def scan() -> None:
    global target
    for ev in drone.events():
        m = CREEP.search(ev)
        if m:
            target = (int(m.group(1)), int(m.group(2)))


drone.takeoff(6)
while True:
    scan()
    if not drone.armed:  # crashed and respawned on the pad: back up we go
        drone.takeoff(6)
    if target is None:
        time.sleep(0.5)  # wait for a creep call
        continue
    n, e = target
    dist = max(1.0, math.hypot(n, e))  # lead toward the Keep at (0, 0)
    an, ae = n - LEAD * n / dist, e - LEAD * e / dist
    # walls are solid from the side and up to 8 m tall: cross the map high,
    # drop onto the creep only once overhead (the zap wants < 3 m above it)
    pn, pe, _alt = drone.position()
    drone.goto(an, ae, 2 if math.hypot(pn - an, pe - ae) < 8 else CRUISE, wait=False)
    settle = time.time() + 2.5
    while time.time() < settle:
        scan()
        if target != (n, e):
            break  # fresher call: re-aim now
        pn, pe, alt = drone.position()
        if alt > 4 and math.hypot(pn - an, pe - ae) < 8:
            drone.goto(an, ae, 2, wait=False)  # overhead: down to zap height
        time.sleep(0.2)
