"""Demo bot: builds watchtowers in the siege game by listening to GAME: messages.

Ferry loop: hover low at the quarry until steel lands in your hands, then
hover over the announced build site at the right height until the tile
places. Three tiles on one cell and the game says "tower up!". Between
waves the game announces where a tower pays off ("build a tower at N .. E ..");
during a wave this bot keeps stacking at the last site it heard.
"""

import re
import time

from dronelife import connect, position_in

SITE = re.compile(r"build a tower at N")
HOVER = re.compile(r"hover (\d+) m to place")

drone = connect()
quarry: tuple[int, int] | None = None
site: tuple[int, int] | None = None
carrying = False
stacked = 0  # tiles we have put on the current site (the hover height grows)
hover_alt: int | None = None  # the game's own altitude hint, when it gives one


def scan() -> None:
    global quarry, site, carrying, stacked, hover_alt
    for ev in drone.events():
        if ev.startswith("quarry at"):
            quarry = position_in(ev)
        elif SITE.search(ev):
            new_site = position_in(ev)
            if new_site != site:
                site, stacked, hover_alt = new_site, 0, None
        elif "got steel" in ev:
            carrying = True
        elif "placed!" in ev:
            carrying, stacked = False, stacked + 1
        elif "tower up" in ev:
            carrying, site, stacked = False, None, 0  # done here: wait for the next site
        elif "steel lost" in ev or "can't build" in ev:
            carrying = False
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
    elif carrying and site:
        alt = hover_alt or 4 + 2 * stacked  # mid-window over the growing stack
        drone.goto(site[0], site[1], alt)
        deadline = time.time() + 8
        while carrying and time.time() < deadline:
            scan()
            time.sleep(0.2)
    else:
        time.sleep(0.5)  # wait for the next announcement
