"""Demo bot: the repair crew in the siege game.

When a creep chews a wall the game says "steel chewed at N .. E .." (or
clay) to everyone, and to a drone carrying the right tile nearby it says
"repair at N .. E .. hover 6" every few seconds. This bot ferries steel
from the quarry to the most recent chewed cell it heard, hovering at the
altitude the game names. Naive on purpose: it always takes the newest
chew, never the nearest, and forgets the target once a tile lands — a
smarter crew keeps a list and sorts it by distance.
"""

import re
import time

from dronelife import connect, position_in

CHEWED = re.compile(r"^steel chewed at N")
REPAIR = re.compile(r"^repair at N (-?\d+) E (-?\d+) hover (\d+)")
HOVER = re.compile(r"hover (\d+) m to place")

drone = connect()
quarry: tuple[int, int] | None = None
target: tuple[int, int] | None = None
hover_alt = 4
carrying = False


def scan() -> None:
    global quarry, target, hover_alt, carrying
    for ev in drone.events():
        if ev.startswith("quarry at"):
            quarry = position_in(ev)
        elif CHEWED.match(ev):
            target, hover_alt = position_in(ev), 4  # the newest hole wins
        elif "got steel" in ev:
            carrying = True
        elif ev.startswith("repaired!") or "placed!" in ev:
            carrying, target = False, None
        elif "steel lost" in ev or "can't build" in ev:
            carrying = False
        m = REPAIR.match(ev)
        if m:
            target, hover_alt = (int(m.group(1)), int(m.group(2))), int(m.group(3))
        m = HOVER.search(ev)
        if m:
            hover_alt = int(m.group(1))


drone.takeoff(8)
while True:
    scan()
    if not drone.armed:  # crashed and respawned on the pad: back up we go
        drone.takeoff(8)
    if not carrying and quarry:
        drone.goto(quarry[0], quarry[1], 2)  # hover low: the pickup dwell
        deadline = time.time() + 8
        while not carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    elif carrying and target:
        drone.goto(target[0], target[1], hover_alt)  # the place dwell at the named height
        deadline = time.time() + 8
        while carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    else:
        time.sleep(0.5)  # nothing chewed yet: wait for it
