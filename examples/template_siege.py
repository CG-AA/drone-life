"""Siege starter: defend the Keep. Edit and press Run.

Creeps march on the Keep at north=0, east=0 from the gates at the arena's
edge. Three ways to fight (all on the cheat sheet):

    ZAP     hover LOW (within 3 m above the creep) and within 4 m of it
            for 1.5 s — the game says "zap! creep down +2"
    SQUISH  carry a steel tile from the quarry and drop it on a creep
    TOWER   stack 3 steel on one cell: a watchtower that shoots by itself

Every few seconds the game tells you where your nearest creep is:
    "creep at N 40 E -12"
That is where it WAS — creeps keep walking toward the Keep, so this script
aims a little ahead of the callout. Ideas: camp a gate, guard the Keep,
lead the target further, or build towers where the creeps walk.
"""

import math
import time

from dronelife import connect, position_in

LEAD = 5.0          # meters ahead of the callout, toward the Keep
ZAP_ALT = 2         # hover this low to zap (creeps on a wall need a bit more)
HUNT_SECONDS = 600  # come home after this long

drone = connect()


def aim_ahead(north, east):
    """The callout is where the creep was; it walks toward (0, 0)."""
    dist = max(1.0, math.hypot(north, east))
    return north - LEAD * north / dist, east - LEAD * east / dist


drone.takeoff(6)
drone.goto(8, 8, 6)   # guard position next to the Keep
print("guarding the Keep — waiting for a creep callout")

target = None
stop_at = time.time() + HUNT_SECONDS
while time.time() < stop_at:
    for msg in drone.events():
        if msg.startswith("creep at"):
            target = position_in(msg)
        elif msg.startswith("zap!"):
            print("got one:", msg)
    if target is None:
        drone.wait(0.5)             # no creeps yet (the game starts with a grace period)
        continue
    n, e = aim_ahead(*target)
    drone.goto(n, e, ZAP_ALT, wait=False)
    drone.wait(2)                   # 1.5 s inside the zap circle is a kill

drone.rtl()
