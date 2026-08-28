"""Co-op delivery: hover low over a crate to grab it, carry it to the dropoff
pad at (0,0), score for the whole class. v1's original content, now composed
from the building.py dwell/carry primitives instead of inlining them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import hex
from ..building import (
    PICKUP_ALT,
    PICKUP_DWELL,
    TOO_HIGH_SAY,
    CarrySlots,
    DwellTracker,
    HintThrottle,
    HoverHint,
    SourceHints,
)
from ..hex import Axial
from ..mission import Entity, Mission, WorldAPI, fmt_world

CRATE_COUNT = 3  # floor: crates alive even in an empty room
CRATE_MAX = 8
PILOTS_PER_CRATE = 3  # one crate in the air per this many connected pilots
SPAWN_STAGGER_S = 2.0  # top-up spawns spread out, never one announce burst
# deliberately tighter than building.PICKUP_RADIUS (2.5): a crate is a precise
# grab, a quarry is a generous pile
PICKUP_RADIUS = 2.0  # m horizontal
DROP_RADIUS = 3.0
DROP_DWELL = 1.0
POINTS = 10
ANNOUNCE_EVERY = 20.0  # re-broadcast crate positions for late joiners
MIN_SPAWN_DIST = 15.0  # from pads, dropoff, other crates
SPAWN_MARGIN = 15.0  # keep away from arena walls
DROPOFF_CELL: Axial = (0, 0)
DROPOFF = hex.axial_to_world(DROPOFF_CELL)

FULL_SAY = f"GAME: hands full, drop at {fmt_world(*DROPOFF)}"
EMPTY_SAY = "GAME: no crate! grab one first"
LOST_SAY = "GAME: crate lost, grab another"
EMPTY_HINT_SUSTAIN = 3.0  # generous: a fresh deliverer lingering isn't nagged


def _pickup_dwell() -> DwellTracker:
    return DwellTracker(PICKUP_RADIUS, PICKUP_ALT, PICKUP_DWELL)


@dataclass
class Crate:
    id: str
    n: float
    e: float
    carried_by: str | None = None  # drone id
    dwell: DwellTracker = field(default_factory=_pickup_dwell)
    last_announce: float = 0.0
    hints: SourceHints | None = None  # wired at spawn (needs mission state)


class DeliveryMission(Mission):
    name = "delivery"

    def __init__(self) -> None:
        self.crates: dict[str, Crate] = {}
        self.delivered = 0  # this round's tally, for the projector strip
        self.carry = CarrySlots()  # drone id -> crate id
        self.drop_dwell = DwellTracker(DROP_RADIUS, PICKUP_ALT, DROP_DWELL)
        self.next_id = 1
        self.last_spawn = float("-inf")
        self.hint_throttle = HintThrottle()  # shared: one nag pace per drone
        self.drop_high = HoverHint(
            DROP_RADIUS, lambda d: self.carry.item(d.id) is not None and d.alt > PICKUP_ALT,
            TOO_HIGH_SAY, "drop_high", self.hint_throttle)
        self.drop_empty = HoverHint(
            DROP_RADIUS, lambda d: self.carry.item(d.id) is None,
            EMPTY_SAY, "drop_empty", self.hint_throttle, sustain=EMPTY_HINT_SUSTAIN)

    # ------------------------------------------------------------- lifecycle

    def hud(self) -> dict:
        return {"crates": len(self.crates), "delivered": self.delivered}

    def setup(self, world: WorldAPI) -> None:
        while len(self.crates) < CRATE_COUNT:
            self._spawn_crate(world)

    def reset(self, world: WorldAPI) -> None:
        self.crates.clear()
        self.delivered = 0
        self.carry.clear()
        self.drop_dwell.clear()
        self.next_id = 1
        self.last_spawn = float("-inf")
        self.hint_throttle.clear()
        self.drop_high.clear()
        self.drop_empty.clear()
        self.setup(world)

    def _desired(self, world: WorldAPI) -> int:
        """Grabbable crates scale with the room: enough that a full class is
        never starved, few enough that a rehearsal with 3 bots feels the same."""
        pilots = sum(1 for d in world.drones() if d.connected)
        return min(CRATE_MAX, max(CRATE_COUNT, math.ceil(pilots / PILOTS_PER_CRATE)))

    def _on_ground(self) -> int:
        """Only a crate nobody is carrying can be flown to. Counting the whole
        population starved a full class: at 20 pilots the target is 7, and once
        7 were in the air nothing on the ground was ever topped up."""
        return sum(1 for c in self.crates.values() if c.carried_by is None)

    def _spawn_crate(self, world: WorldAPI) -> None:
        half = world.config.arena_half - SPAWN_MARGIN
        keep_away = [DROPOFF, *world.config.pad_positions(),
                     *[(c.n, c.e) for c in self.crates.values()]]
        # rejection sampling; under pressure, keep the most isolated sample
        # seen rather than whatever the last draw happened to be
        n = e = 0.0
        best = -1.0
        for _ in range(200):
            cn = world.rng.uniform(-half, half)
            ce = world.rng.uniform(-half, half)
            d = min((math.hypot(cn - kn, ce - ke) for kn, ke in keep_away),
                    default=math.inf)
            if d > best:
                best, n, e = d, cn, ce
            if d >= MIN_SPAWN_DIST:
                break
        crate = Crate(str(self.next_id), n, e)
        crate.hints = SourceHints(self.carry, FULL_SAY, radius=PICKUP_RADIUS,
                                  throttle=self.hint_throttle)
        self.last_spawn = world.now
        self.next_id += 1
        self.crates[crate.id] = crate
        world.emit_event("crate_spawn", f"crate {crate.id} appeared",
                         data={"n": round(n), "e": round(e)})
        self._announce(world, crate)

    def _announce(self, world: WorldAPI, crate: Crate) -> None:
        crate.last_announce = world.now
        world.broadcast_text(f"GAME: crate {crate.id} at {fmt_world(crate.n, crate.e)}")

    # ------------------------------------------------------------------ tick

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = {d.id: d for d in world.drones()}

        # the room grew: top up toward the scaled target, one crate at a time
        if (self._on_ground() < self._desired(world)
                and world.now - self.last_spawn >= SPAWN_STAGGER_S):
            self._spawn_crate(world)

        # per-crate clocks so re-announces stagger instead of bursting
        for crate in self.crates.values():
            if crate.carried_by is None and world.now - crate.last_announce > ANNOUNCE_EVERY:
                self._announce(world, crate)

        # carrier crashed or vanished before delivering: a fresh crate spawns
        # (unless the ground is already at the room's target)
        for drone_id, crate_id in self.carry.sync_losses(drones.values()):
            lost = self.crates.pop(crate_id, None)
            if lost is None:
                continue
            d = drones.get(drone_id)
            reason = "crashed" if (d and d.crashed) else "was lost"
            world.emit_event("crate_lost", f"crate {lost.id} {reason}",
                             student_id=d.student_id if d else None)
            if d is not None:
                world.send_text(d.id, LOST_SAY)
            if self._on_ground() < self._desired(world):
                self._spawn_crate(world)

        # ground crates: hover low + dwell to pick up (one crate per drone)
        for crate in list(self.crates.values()):
            if crate.carried_by is not None:
                continue
            if crate.hints is not None:
                crate.hints.tick(world, drones.values(), crate.n, crate.e, dt)
            winner = crate.dwell.update(drones.values(), crate.n, crate.e, dt,
                                        eligible=lambda d: self.carry.item(d.id) is None)
            if winner is not None:
                crate.carried_by = winner.id
                self.carry.give(winner.id, crate.id)
                world.emit_event("pickup", f"{winner.name} picked up crate {crate.id}",
                                 student_id=winner.student_id)
                world.send_text(winner.id,
                                f"GAME: got crate {crate.id}! "
                                f"drop at {fmt_world(*DROPOFF)}")
                world.broadcast_text(f"GAME: crate {crate.id} taken")

        # the dropoff runs one dwell for whoever is carrying
        self.drop_high.tick(world, drones.values(), *DROPOFF, dt)
        self.drop_empty.tick(world, drones.values(), *DROPOFF, dt)
        winner = self.drop_dwell.update(drones.values(), *DROPOFF, dt,
                                        eligible=lambda d: self.carry.item(d.id) is not None)
        if winner is not None:
            delivered = self.crates.pop(self.carry.take(winner.id) or "", None)
            if delivered is not None:
                self.delivered += 1
                total = world.add_score(POINTS, f"crate {delivered.id} delivered",
                                        student_id=winner.student_id, feed=False)
                world.emit_event("delivery",
                                 f"{winner.name} delivered crate {delivered.id}! +{POINTS}",
                                 student_id=winner.student_id, data={"points": POINTS})
                world.send_text(winner.id, f"GAME: delivered! +{POINTS} (team {total})")
                if self._on_ground() < self._desired(world):
                    self._spawn_crate(world)

    # -------------------------------------------------------------- viewer

    def entities(self, world: WorldAPI) -> list[Entity]:
        pos = {d.id: d for d in world.drones()}
        out = [Entity(id="dropoff", kind="dropoff", n=0.0, e=0.0, alt=0.0)]
        for crate in self.crates.values():
            carrier = pos.get(crate.carried_by or "")
            if carrier is not None:
                out.append(Entity(id=f"crate{crate.id}", kind="crate",
                                  n=carrier.n, e=carrier.e, alt=carrier.alt,
                                  data={"carried_by": crate.carried_by}))
            else:
                out.append(Entity(id=f"crate{crate.id}", kind="crate",
                                  n=crate.n, e=crate.e, alt=0.0))
        return out
