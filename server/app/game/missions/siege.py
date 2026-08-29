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
from typing import Final

from ...sim.backend import DroneView
from .. import hex, path
from ..blueprints import Blueprint, BlueprintTracker, Requirement
from ..building import (
    _EPS,
    HINT_SUSTAIN,
    PICKUP_ALT,
    PICKUP_RADIUS,
    CarrySlots,
    DwellTracker,
    FerryTexts,
    HoverHint,
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
GATE_CELLS: tuple[Axial, ...] = ((-9, 19), (16, 0), (-16, 0))  # N 86 E 3, N 0 E 83, N 0 E -83
GATES = tuple(hex.axial_to_world(c) for c in GATE_CELLS)
GATE_LABELS = ("N", "E", "W")  # what the projector writes on each archway


def _gates_for(wave: int) -> int:
    """How many gates a wave pours through: one lane while the room learns,
    then a pincer, then all three — a single parked drone stops mattering."""
    return 1 if wave <= 3 else 2 if wave <= 7 else 3

CLIMB = 1  # 1 tile is a ramp; a 2-stack is a wall
CHEW_S = 6.0  # s a creep gnaws before a tile pops off
GRACE_S = 45.0  # first-wave delay once a drone shows up: build one tower
BUILD_S = 20.0  # breather between waves
SPAWN_GAP = 1.5  # s between creeps of one wave

KILL_POINTS = 2  # a grunt's bounty (kept as the name the tests and docs know)
WAVE_BONUS = 10  # a clean wave: nothing reached the Keep
WAVE_BONUS_LEAKY = 5  # …and the consolation when something did
TOWER_POINTS = 15
TOWER_BP = Blueprint("watchtower", (Requirement(0, 0, "steel", 3),))
TOWER_HEIGHT = 3
TOWER_RANGE = 16.0
TOWER_COOLDOWN = 2.0
BEAM_S = 0.6  # long enough to be seen from the back row

ZAP_RADIUS = 4.0
ZAP_ALT_ABOVE = 3.0  # hover within this of the creep's feet
ZAP_DWELL = 1.5  # …and between one drone's zaps: a hover kills one creep at a time

# cosmetics the projector draws for a moment: a zap arc from drone to creep,
# a poof where a creep died — same wall-clock expiry discipline as beams
ZAP_ARC_S = 0.3
POOF_S = 0.6

TARGET_EVERY = 3.0  # per-drone nearest-creep hint
ANNOUNCE_EVERY = 30.0
BUILD_HINT_EVERY = 20.0  # 'build a tower at …' while the room has time to build
BUILD_SITE_STEPS = 8  # cells before the Keep along the lane: ~40 m out, where the
# zappers camping the gates have not already emptied the lane (tower range 16)
FERRY = FerryTexts("steel", "GAME: steel lost, grab another",
                   "GAME: got steel, wall or tower it",
                   "GAME: hands full, wall or tower it")

# ------------------------------------------------------------------ economy
# Kills feed a team pool; every wave clear splits the pool evenly into the
# pilots' wallets (personal upgrades spend from there). The pool earns per
# kill *per seated pilot*, so a pilot's income is about the wave's kill count
# whether 6 or 64 people are in the room — the wave cap does not scale with
# the roster, a flat pool split 64 ways would never open the shop.
COINS_PER_KILL_EACH = 1  # pool += this x seated pilots, per kill (leaks pay nothing)
# The quarry is finite: a stock per wave, restocked (not topped up) as each
# wave starts, so a ferry economy exists and hoarded steel is steel unbuilt.
QUARRY_STOCK_BASE = 6
QUARRY_STOCK_PER_PILOT = 1
QUARRY_STOCK_PER_WAVE = 1
QUARRY_EMPTY_SAY = "GAME: quarry empty, restock next wave"


def _quarry_stock(pilots: int, wave: int) -> int:
    """Steel the quarry holds for a wave: 20 pilots at wave 1 see 27 (nine
    towers' worth), a lone rehearsal drone 7; wave 0 is the grace stock."""
    return QUARRY_STOCK_BASE + QUARRY_STOCK_PER_PILOT * pilots + QUARRY_STOCK_PER_WAVE * wave

_HINTS = ("GAME: stack 3 steel = watchtower",
          "GAME: hover low on a creep to zap it",
          "GAME: 2-high walls turn creeps aside",
          "GAME: drop a tile on a creep to squish it",
          "GAME: clean wave +10, each leak costs -1",
          "GAME: towers shoot 16 m, build by the path")


@dataclass
class SiegeStats:
    """This round's tally — the summary the whiteboard used to get by hand."""

    zapped: int = 0
    squished: int = 0
    shot: int = 0  # by towers
    leaks: int = 0
    towers: int = 0
    keep_hits: int = 0
    keep_falls: int = 0
    best_wave: int = 0

    @property
    def kills(self) -> int:
        return self.zapped + self.squished + self.shot

    def as_dict(self) -> dict:
        return {"zapped": self.zapped, "squished": self.squished, "shot": self.shot,
                "kills": self.kills, "leaks": self.leaks, "towers": self.towers,
                "keep_hits": self.keep_hits, "keep_falls": self.keep_falls,
                "best_wave": self.best_wave}


@dataclass
class Tower:
    """A completed watchtower: who raised it (kills credit them), its cooldown."""

    builder: str | None
    last_shot: float = -math.inf  # loaded and ready
    kills: int = 0


# ------------------------------------------------------------------ creeps
# One walker, several kinds: the roster is data. Grunts stay 1 hp so waves
# 1-3 remain the teaching waves; hp pressure arrives with the brutes.

@dataclass(frozen=True)
class CreepKind:
    name: str
    hp: int
    speed_mult: float  # x the wave's base speed
    bounty: int
    chew_rate: float  # x: brutes and sappers eat walls faster
    keep_cost: int  # keep hits when one arrives
    from_wave: int  # first wave it can appear in


KINDS: Final[dict[str, CreepKind]] = {
    "grunt": CreepKind("grunt", hp=1, speed_mult=1.0, bounty=2, chew_rate=1.0,
                       keep_cost=1, from_wave=1),
    "runner": CreepKind("runner", hp=1, speed_mult=1.5, bounty=2, chew_rate=1.0,
                        keep_cost=1, from_wave=3),
    "brute": CreepKind("brute", hp=3, speed_mult=0.65, bounty=5, chew_rate=2.0,
                       keep_cost=1, from_wave=5),
    "sapper": CreepKind("sapper", hp=2, speed_mult=1.0, bounty=3, chew_rate=3.0,
                        keep_cost=1, from_wave=7),
    "champion": CreepKind("champion", hp=8, speed_mult=0.6, bounty=20, chew_rate=2.0,
                          keep_cost=3, from_wave=5),
}
ROSTER_KINDS = ("grunt", "runner", "brute", "sapper")  # champions come by their own rule
# spawn shares per wave band (from wave N: % grunt, runner, brute, sapper)
SHARES: tuple[tuple[int, tuple[int, int, int, int]], ...] = (
    (1, (100, 0, 0, 0)),
    (3, (70, 30, 0, 0)),
    (5, (45, 30, 25, 0)),
    (7, (35, 30, 25, 10)),
    (10, (25, 30, 30, 15)),
)

WAVE_MAX = 20
PILOTS_PER_CREEP = 4  # +1 creep per this many connected pilots
BOSS_EVERY = 5  # a champion walks in behind every 5th wave


def _wave_size(wave: int, pilots: int = 0) -> int:
    """Waves grow with the wave number and with the room: eight optimal
    zappers trivialised the first waves in rehearsal, so a full class meets
    the cap sooner; a lone rehearsal drone still sees four."""
    return min(WAVE_MAX, 4 + 2 * (wave - 1) + pilots // PILOTS_PER_CREEP)


def _wave_speed(wave: int) -> float:
    return min(2.5, 1.5 + 0.1 * (wave - 1))


def _shares(wave: int) -> tuple[int, int, int, int]:
    out = SHARES[0][1]
    for from_wave, shares in SHARES:
        if wave >= from_wave:
            out = shares
    return out


def _wave_roster(wave: int, size: int, rng: random.Random) -> list[str]:
    """`size` kinds for this wave: shares rounded by largest remainder (so
    the composition is exact and deterministic), then shuffled."""
    shares = _shares(wave)
    exact = [size * s / 100 for s in shares]
    counts = [int(x) for x in exact]
    for i in sorted(range(4), key=lambda i: exact[i] - counts[i], reverse=True)[
            : size - sum(counts)]:
        counts[i] += 1
    roster = [k for k, c in zip(ROSTER_KINDS, counts, strict=True) for _ in range(c)]
    rng.shuffle(roster)
    return roster


def _kill_reason(verb: str) -> str:
    return {"zap": "zapped", "squish": "squished", "tower": "shot"}.get(verb, verb)


class SiegeMission(Mission):
    name = "siege"

    def __init__(self) -> None:
        self.tm = TileMap()
        self.carry = CarrySlots()
        self.quarry = TileSource("quarry", *QUARRY, material="steel",
                                 remaining=_quarry_stock(0, 0))
        self.tracker = PlaceTracker(self.tm, self.carry)
        self.blueprints = BlueprintTracker([TOWER_BP])
        self.towers: dict[Axial, Tower] = {}
        self.creeps: dict[int, GroundUnit] = {}
        self.zap: dict[int, DwellTracker] = {}  # creep uid -> hover dwell
        self.zap_ready: dict[str, float] = {}  # drone id -> when its next zap may land
        self.zap_high: dict[int, DwellTracker] = {}  # creep uid -> too-high dwell (a hint)
        # siege's own dice: reseeded from the engine's on every round, so the
        # gate sequence differs between rounds yet stays reproducible per seed
        self.rng = random.Random(0)
        self.round = 0
        self.stats = SiegeStats()
        self.flow = path.flood(self.tm, KEEP_CELL, climb=CLIMB)
        self._flow_version = self.tm.version
        self.keep_hp = KEEP_HP
        self.state = "grace"  # grace | build | active
        self.timer = GRACE_S
        self.wave = 0
        self.gates: tuple[tuple[float, float], ...] = (GATES[0],)  # this wave's lanes
        self.gate = GATES[0]  # the primary lane (first announced)
        self._lane = 0
        self.pending = 0  # creeps of the current wave not yet spawned
        self.roster: list[str] = []  # …and their kinds, in spawn order
        self.spawn_timer = 0.0
        self.leaks = 0  # this wave's creeps that reached the Keep
        self.wave_kills = 0
        self.wave_tower_kills = 0
        self.last_round: dict | None = None  # the record to beat, until wave 1 starts
        self.beams: list[tuple[str, float, tuple, tuple]] = []  # id, expiry, src, dst
        # id, expiry, kind, (n, e, alt), data — see _fx
        self.fx: list[tuple[str, float, str, tuple[float, float, float], dict]] = []
        self._uid = 0
        self._beam_seq = 0
        self._fx_seq = 0
        self._hint = 0
        self.last_announce = 0.0
        self.last_target = 0.0
        self.last_build_hint = float("-inf")
        self.last_brief = float("-inf")  # a periodic announce right after a brief is a dup
        self.site: Axial | None = None  # the suggested tower cell (drawn as a ghost)
        self.hints = SourceHints(self.carry, FERRY.full_say)
        self.place_hints = PlaceHints(self.tm, self.carry, self.hints.throttle)
        # tick_sources skips a spent pile silently: without this, a pilot
        # hovers an empty quarry forever wondering why nothing happens
        self.empty_hint = HoverHint(
            PICKUP_RADIUS,
            lambda d: (self.carry.item(d.id) is None and d.alt <= PICKUP_ALT
                       and self.quarry.remaining == 0),
            QUARRY_EMPTY_SAY, "empty", self.hints.throttle)
        self.pool = 0  # team coins not yet paid out
        self.wallets: dict[str, int] = {}  # student_id -> coins to spend

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        self.tm.set_keep_out([KEEP, QUARRY, *GATES])  # pads are engine-protected already
        self.rng = random.Random(world.rng.getrandbits(32))
        self.quarry.remaining = _quarry_stock(self._seated(world), 0)
        self._announce(world)

    @staticmethod
    def _seated(world: WorldAPI) -> int:
        """Everyone with a drone — connected or between runs. The economy
        counts seats, not live links, so a pilot whose script just ended
        still gets the wave's coins and the quarry stock does not shrink
        because half the room is editing."""
        return len(world.drones())

    def tile_map(self) -> TileMap:
        return self.tm

    def on_drone_event(self, world: WorldAPI, drone: DroneView, kind: str) -> None:
        if kind == "connected":
            self._brief(world, drone)

    def on_text(self, world: WorldAPI, drone: DroneView, text: str) -> None:
        """The command surface: what `drone.say(...)` understands."""
        cmd = " ".join(text.lower().split())
        if cmd == "wallet":
            coins = self.wallets.get(drone.student_id, 0)
            world.send_text(drone.id, f"GAME: wallet {coins} coins")
        else:
            world.send_text(drone.id, "GAME: say wallet")

    def pilot(self, student_id: str) -> dict:
        return {"wallet": self.wallets.get(student_id, 0)}

    def _brief(self, world: WorldAPI, drone: DroneView) -> None:
        """What a newcomer needs, and nothing that already happened: the
        landmarks and where the game is right now."""
        self.last_brief = world.now
        world.send_text(drone.id, f"GAME: keep at {fmt_world(*KEEP)}, protect it!")
        world.send_text(drone.id, f"GAME: quarry at {fmt_world(*QUARRY)}")
        left_s = max(0, math.ceil(self.timer))
        if self.state == "grace":
            world.send_text(drone.id, f"GAME: first wave in {left_s}s, build!")
        elif self.state == "build":
            world.send_text(drone.id, f"GAME: wave {self.wave + 1} in {left_s}s, build!")
        else:
            left = len(self.creeps) + self.pending
            boss = " + boss" if self.wave % BOSS_EVERY == 0 else ""
            world.send_text(
                drone.id,
                f"GAME: wave {self.wave} at {fmt_world(*self.gate)}, {left} creeps{boss}")

    def reset(self, world: WorldAPI) -> None:
        self._round_end(world)
        self.tm.clear()
        self.carry.clear()
        self.tracker.reset()
        self.blueprints.reset()
        self.quarry.dwell.clear()
        self.towers.clear()
        self.creeps.clear()
        self.zap.clear()
        self.zap_high.clear()
        self.zap_ready.clear()
        self.stats = SiegeStats()
        self.round += 1
        self._reflood()
        self.keep_hp = KEEP_HP
        self.state, self.timer, self.wave = "grace", GRACE_S, 0
        self.gates, self.gate, self._lane = (GATES[0],), GATES[0], 0
        self.pending, self.spawn_timer = 0, 0.0
        self.roster.clear()
        self.leaks, self.wave_kills, self.wave_tower_kills = 0, 0, 0
        self.beams.clear()
        self.fx.clear()
        self.last_announce = self.last_target = 0.0
        self.last_build_hint = self.last_brief = float("-inf")
        self.site = None
        self.hints.clear()
        self.place_hints.clear()
        self.empty_hint.clear()
        self.pool = 0
        self.wallets.clear()
        self.setup(world)

    def hud(self) -> dict:
        # integers only: the strip's countdown ticks in whole seconds
        return {
            "stats": self.stats.as_dict(),
            "last_round": self.last_round,
            "wave": self.wave,
            "state": self.state,
            "timer_s": max(0, math.ceil(self.timer)) if self.state != "active" else 0,
            "keep_hp": self.keep_hp,
            "keep_max": KEEP_HP,
            "creeps_alive": len(self.creeps),
            "pending": self.pending,
            "towers": len(self.towers),
            "pool": self.pool,
        }

    # ------------------------------------------------------------------ tick

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = list(world.drones())

        tick_ferry(world, drones, self.carry, [self.quarry], dt, FERRY)
        self.hints.tick(world, drones, *QUARRY, dt)
        self.empty_hint.tick(world, drones, *QUARRY, dt)
        placed, refused = self.tracker.tick(drones, dt)
        self.place_hints.tick(world, drones, dt)
        for p in placed:
            self._squish(world, p)
            match = self.blueprints.check(self.tm, p.cell)
            if match is None:
                world.send_text(p.drone.id, f"GAME: placed! tile at {fmt_cell(p.cell)}")
            else:
                self.towers[match.anchor] = Tower(builder=p.drone.student_id)
                self.stats.towers += 1
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
            for _ in range(u.keep_cost):
                self._keep_hit(world)
        for _u, cell in result.chews:
            if self.tm.remove_top(cell) is not None:
                world.broadcast_text(f"GAME: wall chewed at {fmt_cell(cell)}",
                                     severity=SEV_WARNING)

        self._fire_towers(world)
        self._zap(world, drones, dt)
        self._wave_machine(world, dt)

        if (world.now - self.last_announce > ANNOUNCE_EVERY
                and world.now - self.last_brief > 2.0):  # a newcomer just heard it
            self.last_announce = world.now
            self._announce(world)
        if self.creeps and world.now - self.last_target > TARGET_EVERY:
            self.last_target = world.now
            self._call_targets(world, drones)
        if (self.state in ("grace", "build")
                and world.now - self.last_build_hint > BUILD_HINT_EVERY):
            self.last_build_hint = world.now
            self._call_build_site(world)

    # ---------------------------------------------------------------- combat

    def _squish(self, world: WorldAPI, p) -> None:
        for uid, u in list(self.creeps.items()):
            if u.cell == p.cell:
                self._damage(world, uid, u.hp, "squish", p.drone)  # a tile is a tile

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
            self._beam_seq += 1
            self.beams.append((f"beam{self._beam_seq}", world.now + BEAM_S,
                               (tn, te, self.tm.top_alt(cell)), (u.n, u.e, u.alt)))
            # one shot, one hp: a brute takes three. Kills score quietly (the
            # wave-clear line carries the tally), credited to the builder
            if self._damage(world, target[1], 1, "tower", None, student_id=tower.builder):
                tower.kills += 1
                self.wave_tower_kills += 1

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
                # one zap per drone per dwell: a hover over a clump takes the
                # creeps one at a time (this one's dwell just restarted), so a
                # parked drone is not an area weapon and splitting up pays
                if world.now < self.zap_ready.get(winner.id, -math.inf):
                    continue
                self.zap_ready[winner.id] = world.now + ZAP_DWELL - _EPS
                self._fx(world, "zap_arc", winner.n, winner.e, winner.alt, ZAP_ARC_S,
                         {"tn": u.n, "te": u.e, "talt": u.alt})
                # the dwell re-armed itself: another 1.5 s takes the next hp
                self._damage(world, uid, 1, "zap", winner)

    def _damage(self, world: WorldAPI, uid: int, dmg: int, verb: str,
                drone: DroneView | None, student_id: str | None = None) -> bool:
        """Hurt a creep; on death, pay its bounty and tell the drone that did
        it. Returns True on a kill. Tower hits pass no drone (nobody hears a
        text) but do pass the builder to credit."""
        u = self.creeps.get(uid)
        if u is None:
            return False
        u.hp -= dmg
        if u.hp > 0:
            if drone is not None and verb == "zap":
                world.send_text(drone.id, f"GAME: zap! {u.kind} hp {u.hp}")
            return False
        self._kill(world, uid, verb)
        self.pool += COINS_PER_KILL_EACH * self._seated(world)
        who = drone.student_id if drone is not None else student_id
        # the feed row names the pilot: "+2: Alice zapped a grunt" is the
        # 'that was me' moment for twenty people at once; tower shots stay quiet
        reason = (f"{drone.name} {_kill_reason(verb)} a {u.kind}" if drone is not None
                  else f"{u.kind} {_kill_reason(verb)}")
        world.add_score(u.bounty, reason, student_id=who,
                        feed=drone is not None and u.kind != "champion")
        if u.kind == "champion":  # the boss going down is a moment for the wall
            slayer = drone.name if drone is not None else "a watchtower"
            world.emit_event("boss_down", f"{slayer} felled the champion! +{u.bounty}",
                             student_id=who, data={"points": u.bounty, "wave": self.wave})
            world.broadcast_text(f"GAME: champion down! +{u.bounty}")
        if drone is not None:
            if verb == "zap":
                world.send_text(drone.id, f"GAME: zap! {u.kind} down +{u.bounty}")
            elif verb == "squish":
                world.send_text(drone.id, f"GAME: squish! {u.kind} under tile +{u.bounty}")
        return True

    def _kill(self, world: WorldAPI, uid: int, verb: str) -> None:
        """Remove a creep; `verb` (zap | squish | tower | leak) colours the poof."""
        u = self.creeps.pop(uid, None)
        self.zap.pop(uid, None)
        self.zap_high.pop(uid, None)
        if u is not None:
            if verb == "zap":
                self.stats.zapped += 1
            elif verb == "squish":
                self.stats.squished += 1
            elif verb == "tower":
                self.stats.shot += 1
            else:
                self.stats.leaks += 1
            if verb != "leak":
                self.wave_kills += 1
            self._fx(world, "poof", u.n, u.e, u.alt, POOF_S, {"verb": verb})

    def _fx(self, world: WorldAPI, kind: str, n: float, e: float, alt: float,
            ttl: float, data: dict | None = None) -> None:
        self._fx_seq += 1
        self.fx.append((f"{kind}{self._fx_seq}", world.now + ttl, kind, (n, e, alt), data or {}))

    def _keep_hit(self, world: WorldAPI) -> None:
        self.keep_hp -= 1
        self.stats.keep_hits += 1
        if self.keep_hp > 0:
            world.add_score(KEEP_HIT_POINTS, "keep hit", feed=False)
            world.emit_event("keep_hit",
                             f"the keep took a hit — hp {self.keep_hp}, {KEEP_HIT_POINTS}",
                             data={"points": KEEP_HIT_POINTS, "hp": self.keep_hp})
            world.broadcast_text(f"GAME: keep hit! hp {self.keep_hp}, {KEEP_HIT_POINTS}",
                                 severity=SEV_WARNING)
        else:
            self.keep_hp = KEEP_HP  # co-op never hard-fails: pay and rebuild
            self.stats.keep_falls += 1
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
            share = self._pay_wallets(world)
            by_towers = (f" ({self.wave_tower_kills} by towers)"
                         if self.wave_tower_kills else "")
            coins = f", {share} coin{'s' if share != 1 else ''} each" if share else ""
            world.emit_event(
                "wave_clear",
                f"wave {self.wave} beaten! {self.wave_kills} kills{by_towers}, "
                f"{self.leaks} leaked, +{bonus}{coins}",
                data={"points": bonus, "kills": self.wave_kills, "leaks": self.leaks,
                      "tower_kills": self.wave_tower_kills, "share": share,
                      "pool": self.pool})
            if self.leaks == 0:
                world.broadcast_text(f"GAME: wave {self.wave} clear! +{bonus}")
            else:
                world.broadcast_text(
                    f"GAME: wave {self.wave} clear, {self.leaks} leaked +{bonus}")
            self.state, self.timer = "build", BUILD_S
            world.broadcast_text(f"GAME: wave {self.wave + 1} in {round(BUILD_S)}s, build!")
            self.last_build_hint = world.now
            self._call_build_site(world)

    def _pay_wallets(self, world: WorldAPI) -> int:
        """Split the pool evenly among the seats; the remainder carries.
        Returns the share each pilot got (0: nothing to split yet)."""
        seated = list(world.drones())
        share = self.pool // len(seated) if seated else 0
        if share <= 0:
            return 0
        self.pool -= share * len(seated)
        for d in seated:
            self.wallets[d.student_id] = self.wallets.get(d.student_id, 0) + share
            # widest: "GAME: +999 coins, wallet 9999" = 30
            world.send_text(d.id, f"GAME: +{share} coins, wallet {self.wallets[d.student_id]}")
        return share

    def _start_wave(self, world: WorldAPI, wave: int) -> None:
        self.state, self.wave = "active", wave
        self.stats.best_wave = max(self.stats.best_wave, wave)
        self.quarry.remaining = _quarry_stock(self._seated(world), wave)
        world.broadcast_text(f"GAME: quarry restocked, {self.quarry.remaining} steel")
        k = _gates_for(wave)
        self.gates = tuple(self.rng.sample(GATES, k))
        self.gate, self._lane = self.gates[0], 0
        pilots = sum(1 for d in world.drones() if d.connected)
        size = _wave_size(wave, pilots)
        self.roster = _wave_roster(wave, size, self.rng)
        boss = wave % BOSS_EVERY == 0
        if boss:
            self.roster.append("champion")  # last through the gate, on top of the size
        self.pending = len(self.roster)
        self.leaks, self.wave_kills, self.wave_tower_kills = 0, 0, 0
        self.spawn_timer = 0.0
        if wave == 1:
            self.last_round = None  # the new round is on; the record moves to the whiteboard
        suffix = (f" from {k} gates" if k > 1 else "") + (" + a champion" if boss else "")
        world.emit_event("wave_start", f"wave {wave}: {size} creeps{suffix}",
                         data={"wave": wave, "size": size, "boss": boss, "gates": k})
        # one line per gate, each bot-parseable on its own (a 3-gate line would
        # be 58 chars). Spawns round-robin the lanes, so lane i gets
        # size//k (+1 for the first size%k lanes) — say exactly that.
        # widest: "GAME: wave 10 at N 0 E -83, 20 creeps + boss" = 45
        for i, gate in enumerate(self.gates):
            share = size // k + (1 if i < size % k else 0)
            where = "at" if i == 0 else "also at"
            world.broadcast_text(
                f"GAME: wave {wave} {where} {fmt_world(*gate)}, {share} creeps"
                + (" + boss" if boss and i == 0 else ""))

    def _spawn_creep(self) -> None:
        self._uid += 1
        self.pending -= 1
        kind = KINDS[self.roster.pop(0) if self.roster else "grunt"]
        n, e = self.gates[self._lane % len(self.gates)]
        self._lane += 1
        self.creeps[self._uid] = GroundUnit(
            uid=self._uid, n=n, e=e, speed=_wave_speed(self.wave) * kind.speed_mult,
            kind=kind.name, hp=kind.hp, max_hp=kind.hp, bounty=kind.bounty,
            keep_cost=kind.keep_cost, chew_rate=kind.chew_rate)

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

    def _round_end(self, world: WorldAPI) -> None:
        """A reset after play is a round boundary: say how it went, once, on
        the projector (overlay + feed) and to every drone still listening. A
        reset of a fresh room (nobody played) stays silent."""
        if self.wave == 0 and self.stats.kills == 0 and self.stats.towers == 0:
            return
        st = self.stats
        world.emit_event(
            "round_end",
            f"round over: wave {st.best_wave}, {st.kills} kills, {st.leaks} leaked, "
            f"{world.score} points",
            data={**st.as_dict(), "score": world.score, "round": self.round + 1})
        world.broadcast_text(f"GAME: round over! wave {st.best_wave}, {st.kills} kills")
        self.last_round = {"round": self.round + 1, "wave": st.best_wave,
                           "kills": st.kills, "score": world.score}

    # ---------------------------------------------------------- announcements

    def _announce(self, world: WorldAPI) -> None:
        world.broadcast_text(f"GAME: keep at {fmt_world(*KEEP)}, protect it!")
        world.broadcast_text(f"GAME: quarry at {fmt_world(*QUARRY)}")
        world.broadcast_text(_HINTS[self._hint])
        self._hint = (self._hint + 1) % len(_HINTS)

    def build_site(self) -> Axial | None:
        """Where a tower pays off right now: beside the lane creeps last used,
        BUILD_SITE_STEPS cells before the Keep — off the path itself (a tower
        on the path is what gets chewed), placeable, not already a tower."""
        cell = hex.world_to_axial(*self.gate)
        lane: list[Axial] = []
        while cell != KEEP_CELL and len(lane) < 200:
            nxt = self.flow.toward(cell)
            if nxt is None:
                break
            lane.append(cell)
            cell = nxt
        if len(lane) <= BUILD_SITE_STEPS:
            return None
        anchor = lane[-BUILD_SITE_STEPS]
        on_lane = set(lane)
        for nb in hex.neighbors(anchor):
            if (nb not in on_lane and nb not in self.towers
                    and nb not in self.blueprints.claimed
                    and self.tm.can_place(nb, "steel")[0]):
                return nb
        return None

    def _call_build_site(self, world: WorldAPI) -> None:
        self.site = self.build_site()
        if self.site is not None:  # widest: "GAME: build a tower at N -100 E -100" = 37
            world.broadcast_text(f"GAME: build a tower at {fmt_cell(self.site)}")

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
        for i, (gate, label) in enumerate(zip(GATES, GATE_LABELS, strict=True)):
            active = self.state == "active" and gate in self.gates and self.pending > 0
            out.append(Entity(id=f"gate{i}", kind="gate", n=gate[0], e=gate[1], alt=0.0,
                              data={"label": label, "active": active}))
        for uid, u in self.creeps.items():
            out.append(Entity(id=f"creep{uid}", kind="troop", n=u.n, e=u.e, alt=u.alt,
                              data={"dir": u.heading, "chewing": u.chewing,
                                    "kind": u.kind, "hp": u.hp, "max": u.max_hp}))
        # the suggested site, as a ghost the instructor can point at, while
        # there is time to build and until a tower stands there
        if (self.state in ("grace", "build") and self.site is not None
                and self.tm.height(self.site) < TOWER_HEIGHT):
            n, e = hex.axial_to_world(self.site)
            out.append(Entity(id="site", kind="ghost_tile", n=n, e=e,
                              alt=self.tm.top_alt(self.site),
                              data={"material": "steel", "need": TOWER_HEIGHT,
                                    "have": self.tm.height(self.site), "size": hex.HEX_SIZE}))
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
