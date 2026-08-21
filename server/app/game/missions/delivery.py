"""Co-op delivery: hover low over a crate to grab it, carry it to the dropoff
pad at (0,0), score for the whole class. v1's original content, now composed
from the building.py dwell/carry primitives instead of inlining them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..building import CarrySlots, DwellTracker
from ..mission import Entity, Mission, WorldAPI

CRATE_COUNT = 3
PICKUP_RADIUS = 2.0  # m horizontal
PICKUP_ALT = 3.0  # must be below this altitude
PICKUP_DWELL = 2.0  # s hovering in range
DROP_RADIUS = 3.0
DROP_DWELL = 1.0
POINTS = 10
ANNOUNCE_EVERY = 20.0  # re-broadcast crate positions for late joiners
MIN_SPAWN_DIST = 15.0  # from pads, dropoff, other crates
SPAWN_MARGIN = 15.0  # keep away from arena walls
DROPOFF = (0.0, 0.0)


def _pickup_dwell() -> DwellTracker:
    return DwellTracker(PICKUP_RADIUS, PICKUP_ALT, PICKUP_DWELL)


@dataclass
class Crate:
    id: str
    n: float
    e: float
    carried_by: str | None = None  # drone id
    dwell: DwellTracker = field(default_factory=_pickup_dwell)


class DeliveryMission(Mission):
    name = "delivery"

    def __init__(self) -> None:
        self.crates: dict[str, Crate] = {}
        self.carry = CarrySlots()  # drone id -> crate id
        self.drop_dwell = DwellTracker(DROP_RADIUS, PICKUP_ALT, DROP_DWELL)
        self.next_id = 1
        self.last_announce = 0.0
        self._drone_pos: dict[str, tuple[float, float, float]] = {}

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        while len(self.crates) < CRATE_COUNT:
            self._spawn_crate(world)

    def reset(self, world: WorldAPI) -> None:
        self.crates.clear()
        self.carry.clear()
        self.drop_dwell.clear()
        self.next_id = 1
        self.setup(world)

    def _spawn_crate(self, world: WorldAPI) -> None:
        half = world.config.arena_half - SPAWN_MARGIN
        keep_away = [DROPOFF, *world.config.pads,
                     *[(c.n, c.e) for c in self.crates.values()]]
        n = e = 0.0
        for _ in range(200):
            n = world.rng.uniform(-half, half)
            e = world.rng.uniform(-half, half)
            if all(math.hypot(n - kn, e - ke) >= MIN_SPAWN_DIST for kn, ke in keep_away):
                break
        crate = Crate(str(self.next_id), n, e)
        self.next_id += 1
        self.crates[crate.id] = crate
        world.emit_event("crate_spawn", f"crate {crate.id} appeared",
                         data={"n": round(n), "e": round(e)})
        self._announce(world, crate)

    def _announce(self, world: WorldAPI, crate: Crate) -> None:
        world.broadcast_text(f"GAME: crate {crate.id} at N {round(crate.n)} E {round(crate.e)}")

    # ------------------------------------------------------------------ tick

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = {d.id: d for d in world.drones()}
        self._drone_pos = {d.id: (d.n, d.e, d.alt) for d in drones.values()}

        if world.now - self.last_announce > ANNOUNCE_EVERY:
            self.last_announce = world.now
            for crate in self.crates.values():
                if crate.carried_by is None:
                    self._announce(world, crate)

        # carrier crashed or vanished before delivering: a fresh crate spawns
        for drone_id, crate_id in self.carry.sync_losses(drones.values()):
            crate = self.crates.pop(crate_id, None)
            if crate is None:
                continue
            d = drones.get(drone_id)
            reason = "crashed" if (d and d.crashed) else "was lost"
            world.emit_event("crate_lost", f"crate {crate.id} {reason}",
                             student_id=d.student_id if d else None)
            self._spawn_crate(world)

        # ground crates: hover low + dwell to pick up (one crate per drone)
        for crate in list(self.crates.values()):
            if crate.carried_by is not None:
                continue
            winner = crate.dwell.update(drones.values(), crate.n, crate.e, dt,
                                        eligible=lambda d: self.carry.item(d.id) is None)
            if winner is not None:
                crate.carried_by = winner.id
                self.carry.give(winner.id, crate.id)
                world.emit_event("pickup", f"{winner.name} picked up crate {crate.id}",
                                 student_id=winner.student_id)
                world.send_text(winner.id, f"GAME: got crate {crate.id}! drop at N 0 E 0")
                world.broadcast_text(f"GAME: crate {crate.id} taken")

        # the dropoff runs one dwell for whoever is carrying
        winner = self.drop_dwell.update(drones.values(), *DROPOFF, dt,
                                        eligible=lambda d: self.carry.item(d.id) is not None)
        if winner is not None:
            crate = self.crates.pop(self.carry.take(winner.id) or "", None)
            if crate is not None:
                total = world.add_score(POINTS, f"crate {crate.id} delivered",
                                        student_id=winner.student_id)
                world.emit_event("delivery",
                                 f"{winner.name} delivered crate {crate.id}! +{POINTS}",
                                 student_id=winner.student_id, data={"points": POINTS})
                world.send_text(winner.id, f"GAME: delivered! +{POINTS} (team {total})")
                self._spawn_crate(world)

    # -------------------------------------------------------------- viewer

    def entities(self) -> list[Entity]:
        out = [Entity(id="dropoff", kind="dropoff", n=0.0, e=0.0, alt=0.0)]
        for crate in self.crates.values():
            if crate.carried_by and crate.carried_by in self._drone_pos:
                n, e, alt = self._drone_pos[crate.carried_by]
                out.append(Entity(id=f"crate{crate.id}", kind="crate", n=n, e=e, alt=alt,
                                  data={"carried_by": crate.carried_by}))
            else:
                out.append(Entity(id=f"crate{crate.id}", kind="crate",
                                  n=crate.n, e=crate.e, alt=0.0))
        return out
