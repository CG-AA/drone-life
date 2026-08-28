"""Siege: waves of creeps march on the Keep — build, squish, and zap them.

The tower-defense mission, and the tile layer's payoff: walls reroute the
flow field, towers are a blueprint, chewing is `remove_top`. All mechanics
are library primitives (building/blueprints/path/units); this file is
constants, the wave state machine, and GAME texts.

Tick order is load-bearing and fixed: 1 carry losses, 2 quarry pickups,
3 placements (squish, then blueprint -> towers), 4 tower liveness and
5 repath (both on TileMap.version change), 6 spawns, 7 unit steps (arrivals
hit the Keep, chews remove tiles), 8 towers fire, 9 zap dwells, 10 wave
machine, 11 announcements. Squish resolves before zap, so a tile landing on
a creep is the kill that counts. Everything from 6 on pauses while the room
is empty — an idle server can't bleed score.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ...sim.backend import DroneView
from .. import hex, path
from ..blueprints import Blueprint, BlueprintTracker, Requirement
from ..building import (
    HINT_SUSTAIN,
    CarrySlots,
    DwellTracker,
    FerryTexts,
    PlaceHints,
    PlaceTracker,
    SourceHints,
    TileSource,
    fmt_cell,
    tick_ferry,
)
from ..hex import Axial
from ..mission import SEV_WARNING, Entity, Mission, WorldAPI, fmt_world
from ..tiles import TileMap
from ..units import GroundUnit, step_units

# landmarks are cells; meters are derived so nothing ever sits off-lattice
KEEP_CELL: Axial = (0, 0)
KEEP = hex.axial_to_world(KEEP_CELL)
KEEP_HP = 10
KEEP_HIT_POINTS = -1  # hits 1..9: a gradient, so ignoring the Keep is never free
KEEP_FALL_POINTS = -25  # the 10th hit charges only this, then the Keep rebuilds
QUARRY_CELL: Axial = (14, -11)  # ~(-50, 44)
QUARRY = hex.axial_to_world(QUARRY_CELL)
GATE_CELLS: tuple[Axial, ...] = ((-9, 19), (16, 0), (-16, 0))  # ~N 85, ~E 83, ~E -83
GATES = tuple(hex.axial_to_world(c) for c in GATE_CELLS)

CLIMB = 1  # 1 tile is a ramp; a 2-stack is a wall
CHEW_S = 6.0  # s a creep gnaws before a tile pops off
GRACE_S = 45.0  # first-wave delay once a drone shows up: build one tower
BUILD_S = 20.0  # breather between waves
SPAWN_GAP = 1.5  # s between creeps of one wave

KILL_POINTS = 2
WAVE_BONUS = 10  # a clean wave: nothing reached the Keep
WAVE_BONUS_LEAKY = 5  # …and the consolation when something did
TOWER_POINTS = 15
TOWER_BP = Blueprint("watchtower", (Requirement(0, 0, "steel", 3),))
TOWER_HEIGHT = 3
TOWER_RANGE = 12.0
TOWER_COOLDOWN = 3.0
BEAM_S = 0.35

ZAP_RADIUS = 4.0
ZAP_ALT_ABOVE = 3.0  # hover within this of the creep's feet
ZAP_DWELL = 1.5

# cosmetics the projector draws for a moment: a zap arc from drone to creep,
# a poof where a creep died — same wall-clock expiry discipline as beams
ZAP_ARC_S = 0.3
POOF_S = 0.6

TARGET_EVERY = 3.0  # per-drone nearest-creep hint
ANNOUNCE_EVERY = 20.0
FERRY = FerryTexts("steel", "GAME: steel lost, grab another",
                   "GAME: got steel, wall or tower it",
                   "GAME: hands full, wall or tower it")

_HINTS = ("GAME: stack 3 steel = watchtower",
          "GAME: hover low on a creep to zap it",
          "GAME: 2-high walls turn creeps aside",
          "GAME: drop a tile on a creep to squish it",
          "GAME: clean wave +10, each leak costs -1",
          "GAME: towers shoot 12 m, build by the path")


@dataclass
class Tower:
    """A completed watchtower: who raised it (kills credit them), its cooldown."""

    builder: str | None
    last_shot: float = -math.inf  # loaded and ready
    kills: int = 0


def _wave_size(wave: int) -> int:
    return min(16, 4 + 2 * (wave - 1))


def _wave_speed(wave: int) -> float:
    return min(2.5, 1.5 + 0.1 * (wave - 1))


class SiegeMission(Mission):
    name = "siege"

    def __init__(self) -> None:
        self.tm = TileMap()
        self.carry = CarrySlots()
        self.quarry = TileSource("quarry", *QUARRY, material="steel")
        self.tracker = PlaceTracker(self.tm, self.carry)
        self.blueprints = BlueprintTracker([TOWER_BP])
        self.towers: dict[Axial, Tower] = {}
        self.creeps: dict[int, GroundUnit] = {}
        self.zap: dict[int, DwellTracker] = {}  # creep uid -> hover dwell
        self.zap_high: dict[int, DwellTracker] = {}  # creep uid -> too-high dwell (a hint)
        # siege's own dice: reseeded from the engine's on every round, so the
        # gate sequence differs between rounds yet stays reproducible per seed
        self.rng = random.Random(0)
        self.round = 0
        self.flow = path.flood(self.tm, KEEP_CELL, climb=CLIMB)
        self._flow_version = self.tm.version
        self.keep_hp = KEEP_HP
        self.state = "grace"  # grace | build | active
        self.timer = GRACE_S
        self.wave = 0
        self.gate = GATES[0]
        self.pending = 0  # creeps of the current wave not yet spawned
        self.spawn_timer = 0.0
        self.leaks = 0  # this wave's creeps that reached the Keep
        self.wave_kills = 0
        self.beams: list[tuple[str, float, tuple, tuple]] = []  # id, expiry, src, dst
        # id, expiry, kind, (n, e, alt), data — see _fx
        self.fx: list[tuple[str, float, str, tuple[float, float, float], dict]] = []
        self._uid = 0
        self._beam_seq = 0
        self._fx_seq = 0
        self._hint = 0
        self.last_announce = 0.0
        self.last_target = 0.0
        self.hints = SourceHints(self.carry, FERRY.full_say)
        self.place_hints = PlaceHints(self.tm, self.carry, self.hints.throttle)

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        self.tm.set_keep_out([KEEP, QUARRY, *GATES])  # pads are engine-protected already
        self.rng = random.Random(world.rng.getrandbits(32))
        self._announce(world)

    def tile_map(self) -> TileMap:
        return self.tm

    def reset(self, world: WorldAPI) -> None:
        self.tm.clear()
        self.carry.clear()
        self.tracker.reset()
        self.blueprints.reset()
        self.quarry.dwell.clear()
        self.towers.clear()
        self.creeps.clear()
        self.zap.clear()
        self.zap_high.clear()
        self.round += 1
        self._reflood()
        self.keep_hp = KEEP_HP
        self.state, self.timer, self.wave = "grace", GRACE_S, 0
        self.pending, self.spawn_timer = 0, 0.0
        self.leaks, self.wave_kills = 0, 0
        self.beams.clear()
        self.fx.clear()
        self.last_announce = self.last_target = 0.0
        self.hints.clear()
        self.place_hints.clear()
        self.setup(world)

    def hud(self) -> dict:
        # integers only: the strip's countdown ticks in whole seconds
        return {
            "wave": self.wave,
            "state": self.state,
            "timer_s": max(0, math.ceil(self.timer)) if self.state != "active" else 0,
            "keep_hp": self.keep_hp,
            "keep_max": KEEP_HP,
            "creeps_alive": len(self.creeps),
            "pending": self.pending,
            "towers": len(self.towers),
        }

    # ------------------------------------------------------------------ tick

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = list(world.drones())

        tick_ferry(world, drones, self.carry, [self.quarry], dt, FERRY)
        self.hints.tick(world, drones, *QUARRY, dt)
        placed, refused = self.tracker.tick(drones, dt)
        self.place_hints.tick(world, drones, dt)
        for p in placed:
            self._squish(world, p)
            match = self.blueprints.check(self.tm, p.cell)
            if match is None:
                world.send_text(p.drone.id, f"GAME: placed! tile at {fmt_cell(p.cell)}")
            else:
                self.towers[match.anchor] = Tower(builder=p.drone.student_id)
                world.add_score(TOWER_POINTS, f"watchtower at {fmt_cell(match.anchor)}",
                                student_id=p.drone.student_id, feed=False)
                world.emit_event("tower_up",
                                 f"{p.drone.name} raised a watchtower! +{TOWER_POINTS}",
                                 student_id=p.drone.student_id,
                                 data={"points": TOWER_POINTS})
                world.broadcast_text(f"GAME: tower up! +{TOWER_POINTS}")
        for d, _cell in refused:
            world.send_text(d.id, "GAME: can't build there")

        if self.tm.version != self._flow_version:
            self._check_towers(world)
            self._reflood()

        # beams and fx are wall-clock cosmetics (world.now keeps advancing), so
        # they expire even while an empty room holds the siege clocks still below
        self.beams = [b for b in self.beams if b[1] > world.now]
        self.fx = [f for f in self.fx if f[1] > world.now]

        if not any(d.connected for d in drones):
            return  # empty room: creeps, waves, and clocks all hold still

        if self.state == "active" and self.pending > 0:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_timer += SPAWN_GAP
                self._spawn_creep()

        result = step_units(self.creeps.values(), self.tm, self.flow, dt, CHEW_S)
        for u in result.arrived:
            self.leaks += 1
            self._kill(world, u.uid, "leak")
            self._keep_hit(world)
        for _u, cell in result.chews:
            if self.tm.remove_top(cell) is not None:
                world.broadcast_text(f"GAME: wall chewed at {fmt_cell(cell)}",
                                     severity=SEV_WARNING)

        self._fire_towers(world)
        self._zap(world, drones, dt)
        self._wave_machine(world, dt)

        if world.now - self.last_announce > ANNOUNCE_EVERY:
            self.last_announce = world.now
            self._announce(world)
        if self.creeps and world.now - self.last_target > TARGET_EVERY:
            self.last_target = world.now
            self._call_targets(world, drones)

    # ---------------------------------------------------------------- combat

    def _squish(self, world: WorldAPI, p) -> None:
        for uid, u in list(self.creeps.items()):
            if u.cell == p.cell:
                self._kill(world, uid, "squish")
                world.add_score(KILL_POINTS, "creep squished", student_id=p.drone.student_id)
                world.send_text(p.drone.id, f"GAME: squish! creep under tile +{KILL_POINTS}")

    def _fire_towers(self, world: WorldAPI) -> None:
        for cell in sorted(self.towers):
            tower = self.towers[cell]
            if world.now - tower.last_shot < TOWER_COOLDOWN:
                continue
            tn, te = hex.axial_to_world(cell)
            target = min(
                ((math.hypot(u.n - tn, u.e - te), uid) for uid, u in self.creeps.items()),
                default=None)
            if target is None or target[0] > TOWER_RANGE:
                continue
            u = self.creeps[target[1]]
            tower.last_shot = world.now
            tower.kills += 1
            self._beam_seq += 1
            self.beams.append((f"beam{self._beam_seq}", world.now + BEAM_S,
                               (tn, te, self.tm.top_alt(cell)), (u.n, u.e, u.alt)))
            self._kill(world, target[1], "tower")
            # every 3 s per tower: scored quietly (the wave-clear line carries
            # the tally) and credited to whoever raised the tower
            world.add_score(KILL_POINTS, "tower kill", student_id=tower.builder, feed=False)

    def _zap(self, world: WorldAPI, drones: list[DroneView], dt: float) -> None:
        for uid, u in list(self.creeps.items()):
            ceiling = u.alt + ZAP_ALT_ABOVE  # creeps on walls stay zappable
            # the one silent wrong thing in siege: parked over a creep, too high
            # to zap. Same shape as delivery's TOO_HIGH_SAY, per creep because
            # the creep moves and the ceiling moves with it.
            high = self.zap_high.setdefault(
                uid, DwellTracker(ZAP_RADIUS, float("inf"), HINT_SUSTAIN))

            def too_high(d: DroneView, c: float = ceiling) -> bool:
                return d.alt > c

            nag = high.update(drones, u.n, u.e, dt, eligible=too_high)
            if nag is not None and self.hints.throttle.ready(f"zap_high:{nag.id}", world.now):
                world.send_text(nag.id, f"GAME: drop under {round(ceiling)} m to zap")
            tracker = self.zap.setdefault(uid, DwellTracker(ZAP_RADIUS, 0.0, ZAP_DWELL))
            tracker.max_alt = ceiling
            winner = tracker.update(drones, u.n, u.e, dt)
            if winner is not None:
                self._fx(world, "zap_arc", winner.n, winner.e, winner.alt, ZAP_ARC_S,
                         {"tn": u.n, "te": u.e, "talt": u.alt})
                self._kill(world, uid, "zap")
                world.add_score(KILL_POINTS, "creep zapped", student_id=winner.student_id)
                world.send_text(winner.id, f"GAME: zap! creep down +{KILL_POINTS}")

    def _kill(self, world: WorldAPI, uid: int, verb: str) -> None:
        """Remove a creep; `verb` (zap | squish | tower | leak) colours the poof."""
        u = self.creeps.pop(uid, None)
        self.zap.pop(uid, None)
        self.zap_high.pop(uid, None)
        if u is not None:
            if verb != "leak":
                self.wave_kills += 1
            self._fx(world, "poof", u.n, u.e, u.alt, POOF_S, {"verb": verb})

    def _fx(self, world: WorldAPI, kind: str, n: float, e: float, alt: float,
            ttl: float, data: dict | None = None) -> None:
        self._fx_seq += 1
        self.fx.append((f"{kind}{self._fx_seq}", world.now + ttl, kind, (n, e, alt), data or {}))

    def _keep_hit(self, world: WorldAPI) -> None:
        self.keep_hp -= 1
        if self.keep_hp > 0:
            world.add_score(KEEP_HIT_POINTS, "keep hit", feed=False)
            world.emit_event("keep_hit",
                             f"the keep took a hit — hp {self.keep_hp}, {KEEP_HIT_POINTS}",
                             data={"points": KEEP_HIT_POINTS, "hp": self.keep_hp})
            world.broadcast_text(f"GAME: keep hit! hp {self.keep_hp}, {KEEP_HIT_POINTS}",
                                 severity=SEV_WARNING)
        else:
            self.keep_hp = KEEP_HP  # co-op never hard-fails: pay and rebuild
            world.add_score(KEEP_FALL_POINTS, "the keep fell", feed=False)
            world.emit_event("keep_fell",
                             f"the keep fell! {KEEP_FALL_POINTS}, rebuilt at full hp",
                             data={"points": KEEP_FALL_POINTS})
            world.broadcast_text(f"GAME: keep fell! {KEEP_FALL_POINTS}, rebuilt",
                                 severity=SEV_WARNING)

    # ------------------------------------------------------ waves and towers

    def _wave_machine(self, world: WorldAPI, dt: float) -> None:
        if self.state in ("grace", "build"):
            self.timer -= dt
            if self.timer <= 0:
                self._start_wave(world, self.wave + 1)
        elif self.pending == 0 and not self.creeps:
            bonus = WAVE_BONUS if self.leaks == 0 else WAVE_BONUS_LEAKY
            world.add_score(bonus, f"wave {self.wave} cleared", feed=False)
            world.emit_event(
                "wave_clear",
                f"wave {self.wave} beaten! {self.wave_kills} kills, "
                f"{self.leaks} leaked, +{bonus}",
                data={"points": bonus, "kills": self.wave_kills, "leaks": self.leaks})
            if self.leaks == 0:
                world.broadcast_text(f"GAME: wave {self.wave} clear! +{bonus}")
            else:
                world.broadcast_text(
                    f"GAME: wave {self.wave} clear, {self.leaks} leaked +{bonus}")
            self.state, self.timer = "build", BUILD_S
            world.broadcast_text(f"GAME: wave {self.wave + 1} in {round(BUILD_S)}s, build!")

    def _start_wave(self, world: WorldAPI, wave: int) -> None:
        self.state, self.wave = "active", wave
        self.gate = self.rng.choice(GATES)
        self.pending = _wave_size(wave)
        self.leaks, self.wave_kills = 0, 0
        self.spawn_timer = 0.0
        world.emit_event("wave_start", f"wave {wave}: {self.pending} creeps")
        world.broadcast_text(
            f"GAME: wave {wave} at {fmt_world(*self.gate)}, {self.pending} creeps")

    def _spawn_creep(self) -> None:
        self._uid += 1
        self.pending -= 1
        n, e = self.gate
        self.creeps[self._uid] = GroundUnit(uid=self._uid, n=n, e=e,
                                            speed=_wave_speed(self.wave))

    def _check_towers(self, world: WorldAPI) -> None:
        for cell in [c for c in self.towers if self.tm.height(c) < TOWER_HEIGHT]:
            del self.towers[cell]
            self.blueprints.claimed.discard(cell)  # chewed down: rebuildable
            world.emit_event("tower_down", f"watchtower lost at {fmt_cell(cell)}")
            world.broadcast_text(f"GAME: tower down at {fmt_cell(cell)}",
                                 severity=SEV_WARNING)

    def _reflood(self) -> None:
        self.flow = path.flood(self.tm, KEEP_CELL, climb=CLIMB)
        self._flow_version = self.tm.version

    # ---------------------------------------------------------- announcements

    def _announce(self, world: WorldAPI) -> None:
        world.broadcast_text(f"GAME: keep at {fmt_world(*KEEP)}, protect it!")
        world.broadcast_text(f"GAME: quarry at {fmt_world(*QUARRY)}")
        world.broadcast_text(_HINTS[self._hint])
        self._hint = (self._hint + 1) % len(_HINTS)

    def _call_targets(self, world: WorldAPI, drones: list[DroneView]) -> None:
        for d in drones:
            if not d.connected or not d.armed or d.crashed:
                continue
            u = min(self.creeps.values(),
                    key=lambda u: math.hypot(u.n - d.n, u.e - d.e))
            world.send_text(d.id, f"GAME: creep at {fmt_world(u.n, u.e)}")

    # ----------------------------------------------------------------- viewer

    def entities(self, world: WorldAPI) -> list[Entity]:
        out = [Entity(id="keep", kind="keep", n=KEEP[0], e=KEEP[1], alt=0.0,
                      data={"hp": self.keep_hp, "max": KEEP_HP}),
               self.quarry.entity()]
        for uid, u in self.creeps.items():
            out.append(Entity(id=f"creep{uid}", kind="troop", n=u.n, e=u.e, alt=u.alt,
                              data={"dir": u.heading, "chewing": u.chewing}))
        for cell in self.towers:
            n, e = hex.axial_to_world(cell)
            out.append(Entity(id=f"tower_{cell[0]}_{cell[1]}", kind="tower",
                              n=n, e=e, alt=self.tm.top_alt(cell),
                              data={"range": TOWER_RANGE}))
        for beam_id, _expiry, (n, e, alt), (tn, te, talt) in self.beams:
            out.append(Entity(id=beam_id, kind="beam", n=n, e=e, alt=alt,
                              data={"tn": tn, "te": te, "talt": talt}))
        for fx_id, _expiry, kind, (n, e, alt), data in self.fx:
            out.append(Entity(id=fx_id, kind=kind, n=n, e=e, alt=alt, data=data))
        out.extend(self.carry.entities(world.drones()))
        return out
