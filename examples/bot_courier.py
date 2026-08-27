"""Demo bot: plays the delivery game by listening to GAME: messages.

Doubles as the end-to-end test payload — if this bot can score through the
real container pipeline, students can too.
"""

import random
import re
import time

from dronelife import connect

CRATE = re.compile(r"crate (\d+) at N (-?\d+) E (-?\d+)")

drone = connect()
crates: dict[str, tuple[int, int]] = {}
carrying = False


def scan() -> None:
    global carrying
    for ev in drone.events():
        m = CRATE.search(ev)
        if m:
            crates[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        if "got crate" in ev:
            carrying = True
        if "delivered" in ev:
            carrying = False
        if "crate lost" in ev:
            carrying = False  # crashed with it: the game says so, believe it
        m = re.search(r"crate (\d+) taken", ev)
        if m:
            crates.pop(m.group(1), None)


drone.takeoff(8)
while True:
    scan()
    if carrying:
        drone.goto(0, 0, 2)  # dropoff pad: hover low until the game confirms
        deadline = time.time() + 15
        while carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    elif crates:
        cid, (n, e) = min(crates.items(),
                          key=lambda kv: abs(kv[1][0] - drone.position()[0])
                          + abs(kv[1][1] - drone.position()[1]))
        drone.goto(n, e, 2)  # hover low over the crate to pick it up
        deadline = time.time() + 8
        while not carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
        crates.pop(cid, None)  # picked up or someone beat us to it
    else:
        # no known crates: wander and listen (the game re-announces them)
        drone.goto(random.uniform(-50, 50), random.uniform(-50, 50), 12)
        time.sleep(1)
