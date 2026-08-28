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
    drone.goto(n - LEAD * n / dist, e - LEAD * e / dist, 2, wait=False)
    settle = time.time() + 2.5
    while time.time() < settle:
        scan()
        if target != (n, e):
            break  # fresher call: re-aim now
        time.sleep(0.2)
