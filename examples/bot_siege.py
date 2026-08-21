"""Demo bot: hunts creeps in the siege game by chasing GAME: messages.

Zap loop: fly to the latest announced creep and hover low over it — the
zap dwell does the rest. The game calls out your nearest creep every few
seconds, so keep listening and retarget on every fresh announcement.
"""

import re
import time

from dronelife import connect

CREEP = re.compile(r"creep at N (-?\d+) E (-?\d+)")

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
    if target:
        n, e = target
        drone.goto(n, e, 2)  # hover low on the creep: the zap dwell
        deadline = time.time() + 4
        while time.time() < deadline:
            scan()
            time.sleep(0.2)
    else:
        time.sleep(0.5)  # wait for a creep call
