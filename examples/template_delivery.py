"""Delivery starter: carry crates to the pad. Edit and press Run.

The game tells you where the crates are through drone.events():

    "crate 3 at N -48 E 1"        fly there, hover LOW (under 3 m) for 2 s
    "got crate 3! drop at N 0 E 0" carry it to the pad, hover low 1 s -> +10
    "crate 3 taken"               someone was faster -- wait for the next one

Ideas once this works: go for the NEAREST crate instead of the latest
callout, and use goto(..., wait=False) so a fresher callout can change your
mind mid-flight. The courier bot in the templates menu does both.
"""

import time

from dronelife import connect, position_in

HUNT_SECONDS = 600  # come home after this long

drone = connect()

drone.takeoff(10)
print("waiting for a crate callout")

target = None       # the latest crate callout, as (north, east)
carrying = False
stop_at = time.time() + HUNT_SECONDS
while time.time() < stop_at:
    for msg in drone.events():
        if msg.startswith("crate") and " at " in msg:   # "crate 3 at N -48 E 1"
            target = position_in(msg)
        elif msg.startswith("got crate"):               # "got crate 3! drop at N 0 E 0"
            carrying = True
        elif msg.startswith("delivered"):               # "delivered! +10 (team 30)"
            carrying = False
    if carrying:
        drone.goto(0, 0, 2)                             # hover low over the pad
        drone.wait(1)                                   # ... until the game takes it
    elif target is not None:
        drone.goto(*target, 2)                          # pickups happen below 3 m
        drone.wait(2)
        target = None                                   # picked up, or someone was faster
    else:
        drone.wait(0.5)                                 # no callout yet

drone.rtl()
