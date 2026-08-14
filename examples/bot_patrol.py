"""Demo bot: patrols a square forever. Used for viewer demos and load tests."""

import itertools
import os

from dronelife import connect

# vary altitude and square size by our port so a fleet of bots doesn't stack
port = int(os.environ.get("DRONE_URL", "tcp:127.0.0.1:5760").rsplit(":", 1)[1])
alt = 8 + (port % 10) * 2
r = 25 + (port % 7) * 6

drone = connect()
drone.takeoff(alt)
for n, e in itertools.cycle([(r, r), (r, -r), (-r, -r), (-r, r)]):
    drone.goto(n, e, alt)
