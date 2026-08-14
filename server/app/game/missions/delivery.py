"""Co-op delivery: hover low over a crate to grab it, carry it to the dropoff
pad at (0,0), score for the whole class. All of v1's game content lives here —
everything else is engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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


@dataclass
class Crate:
    id: str
    n: float
    e: float
    carried_by: str | None = None  # drone id
    pickup_dwell: dict[str, float] = field(default_factory=dict)  # drone id -> s
    drop_dwell: float = 0.0


class DeliveryMission(Mission):
    name = "delivery"

    def __init__(self) -> None:
        self.crates: dict[str, Crate] = {}
        self.next_id = 1
        self.last_announce = 0.0
        self._drone_pos: dict[str, tuple[float, float, float]] = {}

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        while len(self.crates) < CRATE_COUNT:
            self._spawn_crate(world)

    def reset(self, world: WorldAPI) -> None:
        self.crates.clear()
        self.next_id = 1
        self.setup(world)

    def _spawn_crate(self, world: WorldAPI) -> None:
        half = world.config.arena_half - SPAWN_MARGIN
        keep_away = [world.config.dropoff, *world.config.pads,
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

        carrying = {c.carried_by for c in self.crates.values() if c.carried_by}
        for crate in list(self.crates.values()):
            if crate.carried_by is None:
                self._tick_ground_crate(world, crate, drones, carrying, dt)
            else:
                self._tick_carried_crate(world, crate, drones, dt)

    def _tick_ground_crate(self, world: WorldAPI, crate: Crate, drones: dict,
                           carrying: set, dt: float) -> None:
        in_range: set[str] = set()
        for d in drones.values():
            if d.id in carrying or not d.armed or d.crashed or d.alt > PICKUP_ALT:
                continue
            if math.hypot(d.n - crate.n, d.e - crate.e) <= PICKUP_RADIUS:
                in_range.add(d.id)
                dwell = crate.pickup_dwell.get(d.id, 0.0) + dt
                crate.pickup_dwell[d.id] = dwell
                if dwell >= PICKUP_DWELL:
                    crate.carried_by = d.id
                    crate.pickup_dwell.clear()
                    world.emit_event("pickup", f"{d.name} picked up crate {crate.id}",
                                     student_id=d.student_id)
                    world.send_text(d.id, f"GAME: got crate {crate.id}! drop at N 0 E 0")
                    world.broadcast_text(f"GAME: crate {crate.id} taken")
                    return
        # leaving the circle resets your dwell timer
        for drone_id in list(crate.pickup_dwell):
            if drone_id not in in_range:
                del crate.pickup_dwell[drone_id]

    def _tick_carried_crate(self, world: WorldAPI, crate: Crate, drones: dict,
                            dt: float) -> None:
        d = drones.get(crate.carried_by)
        if d is None or d.crashed or not d.armed:
            # carrier lost the crate before delivering: fresh one spawns
            reason = "crashed" if (d and d.crashed) else "was lost"
            world.emit_event("crate_lost", f"crate {crate.id} {reason}",
                             student_id=d.student_id if d else None)
            del self.crates[crate.id]
            self._spawn_crate(world)
            return
        dn, de = world.config.dropoff
        if math.hypot(d.n - dn, d.e - de) <= DROP_RADIUS and d.alt <= PICKUP_ALT:
            crate.drop_dwell += dt
            if crate.drop_dwell >= DROP_DWELL:
                total = world.add_score(POINTS, f"crate {crate.id} delivered",
                                        student_id=d.student_id)
                world.emit_event("delivery", f"{d.name} delivered crate {crate.id}! +{POINTS}",
                                 student_id=d.student_id, data={"points": POINTS})
                world.send_text(d.id, f"GAME: delivered! +{POINTS} (team {total})")
                del self.crates[crate.id]
                self._spawn_crate(world)
        else:
            crate.drop_dwell = 0.0

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
