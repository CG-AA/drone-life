"""Worked answer: route quests — parse a multi-line spec, sequence gotos,
and for "any order" pick the order yourself.

    quest 7: route 3 stops, 42 s          visit in the listed order
    quest 7: route back 4 stops, 60 s     …in REVERSE of the listed order
    quest 7: route at 18 m, 4 stops, 60 s at that altitude (±1.5 m), listed order
    quest 7: route any order 5 stops, 90 s any order — the listed one is the slow one
    quest 7 stop 1 at N 20 E -30          one line per stop (any order of arrival)

The stops arrive as separate lines, so a quest is not ready until all of
them are in. "any order" is a tiny travelling-salesman: five stops is 120
permutations, brute force is fine. The game checks a stop within 2.5 m at
any altitude (or the stated one), so goto(tolerance=1.0) is enough.
"""

import itertools
import math
import re
import time

from dronelife import connect

HEAD = re.compile(
    r"^(room )?quest (\d+): route(?: (back|any order|at (\d+) m,))? (\d+) stops, (\d+) s$")
STOP = re.compile(r"^(room )?quest (\d+) stop (\d+) at N (-?\d+) E (-?\d+)$")
OVER = re.compile(r"^(room )?quest (\d+) (solved|expired|off)")

CRUISE_ALT = 10.0  # above every wall (8 m), below nothing that matters

drone = connect()
quests: dict[tuple[bool, int], dict] = {}  # (room?, id) -> spec


def scan() -> None:
    for ev in drone.events():
        m = HEAD.match(ev)
        if m:
            room, qid, variant, alt, count, limit = m.groups()
            quests[(bool(room), int(qid))] = {
                "variant": variant or "", "alt": float(alt) if alt else None,
                "count": int(count), "limit": float(limit), "stops": {}, "flown": False,
            }
            continue
        m = STOP.match(ev)
        if m:
            room, qid, k, n, e = m.groups()
            q = quests.get((bool(room), int(qid)))
            if q is not None:
                q["stops"][int(k)] = (float(n), float(e))
            continue
        m = OVER.match(ev)
        if m:
            quests.pop((bool(m.group(1)), int(m.group(2))), None)


def plan(q: dict, here: tuple[float, float]) -> list[tuple[float, float]]:
    """The order to fly the stops in."""
    listed = [q["stops"][k] for k in sorted(q["stops"])]
    if q["variant"].startswith("back"):
        return listed[::-1]
    if q["variant"] != "any order":
        return listed

    def length(order):
        at, total = here, 0.0
        for p in order:
            total += math.hypot(p[0] - at[0], p[1] - at[1])
            at = p
        return total

    return list(min(itertools.permutations(listed), key=length))


drone.say("quest")
drone.takeoff(CRUISE_ALT)
while True:
    scan()
    if not drone.armed:  # crashed and respawned: back up, the quest is gone
        drone.takeoff(CRUISE_ALT)
    ready = [q for q in quests.values() if len(q["stops"]) == q["count"] and not q["flown"]]
    if not ready:
        time.sleep(0.2)
        continue
    q = ready[0]
    q["flown"] = True
    n0, e0, _ = drone.position()
    alt = q["alt"] or CRUISE_ALT
    deadline = time.time() + q["limit"]
    for n, e in plan(q, (n0, e0)):
        if time.time() > deadline:
            break
        drone.goto(n, e, alt, tolerance=1.0, timeout=max(5.0, deadline - time.time()))
        drone.wait(0.3)  # let the game's 10 Hz check see us inside the circle
