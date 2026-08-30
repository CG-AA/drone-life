"""Demo bot: the scout. Event-driven flying — no blocking goto in the loop.

Hover within 10 m of a gate for 2 s and the game makes you its spotter:
"you spot gate E". From then on every creep through that gate is reported
to you — "gate E: 3 grunt 1 sapper" — and the room hears you on the
projector. This bot parks high (12 m: above the zap ceiling, so it never
kills anything and stays beatable), listens with next_event(), and moves
to whichever gate the latest "wave N at" line names. Leave the circle and
the post is free again ("gate E unwatched").
"""

import re

from dronelife import connect, position_in

WAVE = re.compile(r"^wave \d+ at N")
POST_ALT = 12

drone = connect()
drone.takeoff(POST_ALT)
gate: tuple[int, int] | None = None
while True:
    if not drone.armed:  # crashed and respawned: back up
        drone.takeoff(POST_ALT)
    ev = drone.next_event(timeout=1.0)  # block for the next line, not for arrival
    if ev is None:
        continue
    if WAVE.match(ev):
        where = position_in(ev)
        if where != gate:  # the primary lane moved: re-post
            gate = where
            drone.goto(gate[0], gate[1], POST_ALT, wait=False)
    elif ev.startswith("gate ") or ev.startswith("you spot"):
        print(ev, flush=True)  # what the room is about to hear
