"""Demo bot: plays the rampart game by listening to GAME: messages.

Ferry loop: hover low at the quarry until steel lands in your hands, then
hover at the announced gap and altitude until the wall grows.
"""

import re
import time

from dronelife import connect

QUARRY = re.compile(r"quarry at N (-?\d+) E (-?\d+)")
GAP = re.compile(r"wall gap at N (-?\d+) E (-?\d+) hover (\d+)")

drone = connect()
quarry: tuple[int, int] | None = None
gap: tuple[int, int, int] | None = None
carrying = False


def scan() -> None:
    global quarry, gap, carrying
    for ev in drone.events():
        m = QUARRY.search(ev)
        if m:
            quarry = (int(m.group(1)), int(m.group(2)))
        m = GAP.search(ev)
        if m:
            gap = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if "got steel" in ev:
            carrying = True
        if "placed!" in ev or "steel lost" in ev:
            carrying = False
            gap = None  # the game will announce the next gap


drone.takeoff(8)
while True:
    scan()
    if not carrying and quarry:
        drone.goto(quarry[0], quarry[1], 2)  # hover low: the pickup dwell
        deadline = time.time() + 8
        while not carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    elif carrying and gap:
        n, e, alt = gap
        drone.goto(n, e, alt)  # hover at the announced height: the place dwell
        deadline = time.time() + 8
        while carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    else:
        time.sleep(0.5)  # wait for the next announcement
