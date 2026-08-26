"""Building-game primitives: hover-dwell pickup from sources, carry state,
hover-dwell placement onto cells.

The delivery mission's dwell mechanic, reified: missions compose these — they
do not reimplement them. A build mission contributes constants, an `allowed`
rule, blueprint data, and its GAME texts; everything mechanical lives here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..sim.backend import DroneView
from . import hex
from .hex import Axial
from .mission import Entity, WorldAPI, fmt_world
from .tiles import TILE_HEIGHT, TileMap

PICKUP_RADIUS = 2.5  # m horizontal, at a source
PICKUP_ALT = 3.0  # must hover below this (delivery's feel)
PICKUP_DWELL = 2.0  # s
PLACE_DWELL = 1.5  # s hovering over one cell, inside its height window
PLACE_CLEAR = 0.4  # m a drone must clear a new stack top by (also the crush rule)
PLACE_WINDOW = 3.0  # m above the new stack top where placing works

HINT_SUSTAIN = 1.5  # s of sustained wrongness before a hint speaks
HINT_EVERY = 10.0  # s per drone per hint kind (cf. siege's TARGET_EVERY)
# one phrasing everywhere a low hover is required — students learn it once
TOO_HIGH_SAY = f"GAME: too high, get under {round(PICKUP_ALT)} m"

_EPS = 1e-9  # dt accumulates in floats; N*dt may land a hair under N*dt exactly


@dataclass
class DwellTracker:
    """Point-radius hover dwell: per-drone accumulation, reset on exit."""

    radius: float
    max_alt: float
    dwell_s: float
    acc: dict[str, float] = field(default_factory=dict)

    def update(self, drones: Iterable[DroneView], n: float, e: float, dt: float,
               eligible: Callable[[DroneView], bool] | None = None) -> DroneView | None:
        """Accumulate dwell for drones hovering the point. At most one winner
        per tick; only the winner's timer resets, so a second drone mid-dwell
        finishes on its own schedule."""
        in_range: set[str] = set()
        winner: DroneView | None = None
        for d in drones:
            if not d.armed or d.crashed or d.alt > self.max_alt:
                continue
            if eligible is not None and not eligible(d):
                continue
            if math.hypot(d.n - n, d.e - e) > self.radius:
                continue
            in_range.add(d.id)
            self.acc[d.id] = self.acc.get(d.id, 0.0) + dt
            if winner is None and self.acc[d.id] >= self.dwell_s - _EPS:
                winner = d
        for drone_id in list(self.acc):  # leaving the circle resets your timer
            if drone_id not in in_range:
                del self.acc[drone_id]
        if winner is not None:
            del self.acc[winner.id]
        return winner

    def clear(self) -> None:
        self.acc.clear()


def _pickup_dwell() -> DwellTracker:
    return DwellTracker(PICKUP_RADIUS, PICKUP_ALT, PICKUP_DWELL)


# ------------------------------------------------------------------- hints
# The dwell trackers silently skip a drone that is too high or ineligible —
# correct mechanics, invisible to the student doing it wrong. These speak up.

@dataclass
class HintThrottle:
    """Per-key cooldown so a hint nags, at most, every `every` seconds."""

    every: float = HINT_EVERY
    _last: dict[str, float] = field(default_factory=dict)

    def ready(self, key: str, now: float) -> bool:
        last = self._last.get(key)
        if last is not None and now - last < self.every:
            return False
        self._last[key] = now
        return True

    def clear(self) -> None:
        self._last.clear()


class HoverHint:
    """One nag at one point: a drone matching `wrong` that hovers (n, e) for
    `sustain` seconds hears `say` — a drone just transiting the circle never
    does. Throttled per drone through the shared HintThrottle."""

    def __init__(self, radius: float, wrong: Callable[[DroneView], bool],
                 say: str, kind: str, throttle: HintThrottle,
                 sustain: float = HINT_SUSTAIN) -> None:
        self.wrong = wrong
        self.say = say
        self.kind = kind
        self.throttle = throttle
        self.dwell = DwellTracker(radius, float("inf"), sustain)

    def tick(self, world: WorldAPI, drones: Iterable[DroneView],
             n: float, e: float, dt: float) -> None:
        hit = self.dwell.update(drones, n, e, dt, eligible=self.wrong)
        if hit is not None and self.throttle.ready(f"{self.kind}:{hit.id}", world.now):
            world.send_text(hit.id, self.say)

    def clear(self) -> None:
        self.dwell.clear()


class SourceHints:
    """The two standard nags at a pickup point: hovering it empty-handed but
    too high, and hovering it low with hands already full."""

    def __init__(self, carry: CarrySlots, full_say: str,
                 radius: float = PICKUP_RADIUS,
                 throttle: HintThrottle | None = None) -> None:
        self.throttle = throttle if throttle is not None else HintThrottle()
        self.high = HoverHint(
            radius, lambda d: carry.item(d.id) is None and d.alt > PICKUP_ALT,
            TOO_HIGH_SAY, "high", self.throttle)
        self.full = HoverHint(
            radius, lambda d: carry.item(d.id) is not None and d.alt <= PICKUP_ALT,
            full_say, "full", self.throttle)

    def tick(self, world: WorldAPI, drones: Iterable[DroneView],
             n: float, e: float, dt: float) -> None:
        drones = list(drones)
        self.high.tick(world, drones, n, e, dt)
        self.full.tick(world, drones, n, e, dt)

    def clear(self) -> None:
        self.throttle.clear()
        self.high.clear()
        self.full.clear()


@dataclass
class TileSource:
    """A pile drones collect from by hovering low. remaining=None is infinite."""

    id: str
    n: float
    e: float
    material: str
    remaining: int | None = None
    dwell: DwellTracker = field(default_factory=_pickup_dwell)

    def entity(self) -> Entity:
        return Entity(id=self.id, kind="tile_source", n=self.n, e=self.e, alt=0.0,
                      data={"material": self.material, "remaining": self.remaining})


class CarrySlots:
    """One tile per drone; lost on crash/disarm (delivery's rule, reified)."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def item(self, drone_id: str) -> str | None:
        return self._items.get(drone_id)

    def give(self, drone_id: str, material: str) -> bool:
        if drone_id in self._items:
            return False  # hands full
        self._items[drone_id] = material
        return True

    def take(self, drone_id: str) -> str | None:
        return self._items.pop(drone_id, None)

    def sync_losses(self, drones: Iterable[DroneView]) -> list[tuple[str, str]]:
        """Drop tiles whose carrier crashed, disarmed, or vanished. Call every
        tick; returns (drone_id, material) pairs for mission messaging."""
        alive = {d.id: d for d in drones}
        lost = []
        for drone_id in list(self._items):
            d = alive.get(drone_id)
            if d is None or d.crashed or not d.armed:
                lost.append((drone_id, self._items.pop(drone_id)))
        return lost

    def entities(self, drones: Iterable[DroneView]) -> list[Entity]:
        out = []
        for d in drones:
            material = self._items.get(d.id)
            if material is not None:
                out.append(Entity(id=f"carry_{d.id}", kind="tile_carried",
                                  n=d.n, e=d.e, alt=d.alt,
                                  data={"carried_by": d.id, "material": material}))
        return out

    def clear(self) -> None:
        self._items.clear()


# ------------------------------------------------------- placement geometry

def hover_cell(d: DroneView) -> Axial:
    return hex.world_to_axial(d.n, d.e)


def place_window(tm: TileMap, cell: Axial) -> tuple[float, float]:
    """The (low, high] altitude band where a hovering drone places onto `cell`
    — measured against where the NEW stack top will be."""
    new_top = tm.top_alt(cell) + TILE_HEIGHT
    return new_top + PLACE_CLEAR, new_top + PLACE_WINDOW


def hover_alt_hint(tm: TileMap, cell: Axial) -> int:
    """The whole-meter altitude to tell students: mid-window, 2*height + 4."""
    return 2 * tm.height(cell) + 4


def fmt_cell(cell: Axial) -> str:
    """Cell center in the announce grammar: 'N 10 E -55'."""
    return fmt_world(*hex.axial_to_world(cell))


def crush_ok(tm: TileMap, cell: Axial, drones: Iterable[DroneView],
             placing_id: str) -> bool:
    """Never crush or lift: every OTHER drone over the cell must clear the
    new stack top. (The placer is inside the window by definition.)"""
    new_top = tm.top_alt(cell) + TILE_HEIGHT
    for d in drones:
        if d.id == placing_id:
            continue
        if hex.world_to_axial(d.n, d.e) == cell and d.alt < new_top + PLACE_CLEAR:
            return False
    return True


@dataclass(frozen=True)
class Placement:
    drone: DroneView
    cell: Axial
    material: str


class PlaceTracker:
    """Per-drone cell-dwell placement: stay over ONE cell, inside its height
    window, carrying, for `dwell_s`. Cell change or window exit resets.
    Commits tm.place() itself; missions score and announce the results."""

    def __init__(self, tm: TileMap, carry: CarrySlots,
                 dwell_s: float = PLACE_DWELL,
                 allowed: Callable[[Axial], bool] | None = None) -> None:
        self.tm = tm
        self.carry = carry
        self.dwell_s = dwell_s
        self.allowed = allowed
        self._acc: dict[str, tuple[Axial, float]] = {}  # drone id -> (cell, s)

    def tick(self, drones: Iterable[DroneView], dt: float
             ) -> tuple[list[Placement], list[tuple[DroneView, Axial]]]:
        """-> (committed placements, completed-dwells-on-refused-cells)."""
        drones = list(drones)
        placed: list[Placement] = []
        refused: list[tuple[DroneView, Axial]] = []
        seen: set[str] = set()
        for d in drones:
            material = self.carry.item(d.id)
            if material is None or not d.armed or d.crashed:
                continue
            cell = hover_cell(d)
            low, high = place_window(self.tm, cell)
            if not low <= d.alt <= high:
                continue  # outside the band: state drops in the sweep below
            seen.add(d.id)
            prev_cell, acc = self._acc.get(d.id, (cell, 0.0))
            if prev_cell != cell:
                acc = 0.0  # drifted to another cell: restart there
            acc += dt
            if acc < self.dwell_s - _EPS:
                self._acc[d.id] = (cell, acc)
                continue
            self._acc[d.id] = (cell, 0.0)  # dwell complete: resolve, then rearm
            ok = (self.allowed is None or self.allowed(cell)) \
                and self.tm.can_place(cell, material)[0] \
                and crush_ok(self.tm, cell, drones, d.id)
            if not ok:
                refused.append((d, cell))
                continue
            self.carry.take(d.id)
            self.tm.place(cell, material)
            placed.append(Placement(d, cell, material))
        for drone_id in list(self._acc):  # window/cell exits reset the timer
            if drone_id not in seen:
                del self._acc[drone_id]
        return placed, refused

    def reset(self) -> None:
        self._acc.clear()


def tick_sources(drones: Iterable[DroneView], sources: Iterable[TileSource],
                 carry: CarrySlots, dt: float) -> list[tuple[DroneView, TileSource]]:
    """Run every source's pickup dwell. Empty-handed drones only; a completed
    dwell hands over a tile. Returns (drone, source) pickups for messaging."""
    drones = list(drones)
    pickups = []
    for source in sources:
        if source.remaining is not None and source.remaining <= 0:
            continue
        winner = source.dwell.update(
            drones, source.n, source.e, dt,
            eligible=lambda d: carry.item(d.id) is None)
        if winner is not None and carry.give(winner.id, source.material):
            if source.remaining is not None:
                source.remaining -= 1
            pickups.append((winner, source))
    return pickups


@dataclass(frozen=True)
class FerryTexts:
    """A build mission's flavor for the standard gather loop."""

    material: str  # feed noun: "steel", "clay"
    lost_say: str  # "GAME: steel lost, grab another"
    got_say: str  # "GAME: got steel, place on the wall"
    full_say: str  # "GAME: hands full, place on the wall"


def tick_ferry(world: WorldAPI, drones: Iterable[DroneView], carry: CarrySlots,
               sources: Iterable[TileSource], dt: float, texts: FerryTexts) -> None:
    """The gather preamble every build mission runs: drop tiles whose carrier
    died, run the source pickups, send the standard events and texts."""
    drones = list(drones)
    for _drone_id, _material in carry.sync_losses(drones):
        world.emit_event("tile_lost", f"a {texts.material} tile was lost")
        world.broadcast_text(texts.lost_say)
    for d, _source in tick_sources(drones, sources, carry, dt):
        world.emit_event("pickup", f"{d.name} picked up {texts.material}",
                         student_id=d.student_id)
        world.send_text(d.id, texts.got_say)
