"""Siege: waves of creeps march on the Keep — build, squish, and zap them.

The tower-defense mission, and the tile layer's payoff: walls reroute the
flow field, towers are a blueprint, chewing is `remove_top`. All mechanics
are library primitives (building/blueprints/path/units); this file is
constants, the wave state machine, and GAME texts.

Tick order is load-bearing and fixed: 1 carry losses, 2 quarry pickups,
3 placements (squish, then blueprint -> towers), 4 tower liveness and
5 repath (both on TileMap.version change), 6 spawns, 7 unit steps (arrivals
hit the Keep, chews remove tiles), 8 towers fire, 9 zap dwells, 10 wave
machine, 10b quests (issue, check, expire — after the kills, so a predict
sees live creeps; after the wave machine, so a new wave's gate lines land
before its room quest), 11 announcements. Squish resolves before zap, so a tile landing on
a creep is the kill that counts. Everything from 6 on pauses while the room
is empty — an idle server can't bleed score.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Final

from ...sim.backend import DroneView
from .. import hex, path
from ..blueprints import Blueprint, BlueprintTracker, Requirement, match_at, ring_blueprint
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
    hover_alt_hint,
    tick_ferry,
)
from ..formation import triangle
from ..hex import Axial
from ..mission import SEV_WARNING, Entity, Mission, WorldAPI, fmt_world
from ..path import FlowField
from ..quests import (
    BUFF_HP,
    BUFF_SPEED,
    QUEST_POINTS,
    QUEST_POOL_EACH,
    ROOM_QUEST_POOL_EACH,
    Buff,
    QuestBoard,
    Resolved,
    room_marks,
)
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
PIT_CELL: Axial = (-14, 11)  # ~(50, -44): the quarry mirrored through the Keep
PIT = hex.axial_to_world(PIT_CELL)
# The sealed south gate: a co-op puzzle. Three drones holding a triangle over
# it for FORM_HOLD_S open it for a lane of raiders whose bounty pays the
# team and the pot — never the trio. A row north of the 64-seat pads.
BONUS_GATE_CELL: Axial = (8, -14)  # N -63 E 5
BONUS_GATE = hex.axial_to_world(BONUS_GATE_CELL)
FORM_RADIUS = 12.0  # m of the gate (the pad rows are 13.5 m away)
FORM_MIN = 6.0  # m between any two of the three
FORM_MAX = 12.0
FORM_MIN_ANGLE = 30.0  # degrees: a line of three is not a triangle
FORM_HOLD_S = 5.0
BONUS_LANE_SIZE = 6  # raiders per opening
BONUS_PER_WAVE = 1  # openings
RAIDER_POOL_EACH = 1  # pool += this x seats per raider killed (no personal credit)


def _gates_for(wave: int) -> int:
    """How many gates a wave pours through: one lane while the room learns,
    then a pincer, then all three — a single parked drone stops mattering."""
    return 1 if wave <= 3 else 2 if wave <= 7 else 3

CLIMB = 1  # 1 tile is a ramp; a 2-stack is a wall
CHEW_S = 6.0  # s a creep gnaws before a tile pops off
CHEW_FACTOR = {"steel": 1.0, "clay": 3.0}  # clay is the cheap wall: rerouted the same, eaten fast
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

# ----------------------------------------------------------- more buildings
# Ring a standing watchtower with 6 steel: long range, faster reload. A ring
# is 1 high (creeps walk over it; only the centre being chewed drops it).
RING_BP = Blueprint("ring_tower", (Requirement(0, 0, "steel", TOWER_HEIGHT),
                                   *ring_blueprint("ring", "steel").reqs))
RING_RANGE = 28.0
RING_COOLDOWN = 1.5
RING_POINTS = 25
# A beacon lures creeps: a clay-steel-clay line, each cell exactly 1 high
# (a 2-stack is a wall, a 3-stack the tower — max_height keeps them apart).
BEACON_BP = Blueprint("beacon", (Requirement(0, 0, "steel", 1, max_height=1),
                                 Requirement(1, 0, "clay", 1, max_height=1),
                                 Requirement(-1, 0, "clay", 1, max_height=1)))
BEACON_MAX = 2  # standing at once (each one is its own flow field)
BEACON_RADIUS = 25.0  # m: creeps this close walk to the beacon, not the Keep
LURE_BONUS_EACH = 1  # pool += this x seats per creep killed while lured
# The Bell: 3 clay in the middle of a 6-clay ring, rung by hovering on top.
# One shot: every creep freezes for FREEZE_S, then the bell is spent.
BELL_BP = Blueprint("bell", (Requirement(0, 0, "clay", 3), *ring_blueprint("bell", "clay").reqs))
BELL_RADIUS = 2.5
BELL_ALT_ABOVE = 3.0  # hover within this of the stack top (6 m): "hover 8 m"
BELL_DWELL_S = 3.0
BELL_RING_S = 1.2  # the visible ring
FREEZE_S = 15.0

ZAP_RADIUS = 4.0
ZAP_ALT_ABOVE = 3.0  # hover within this of the creep's feet
ZAP_DWELL = 1.5  # …and between one drone's zaps: a hover kills one creep at a time

# cosmetics the projector draws for a moment: a zap arc from drone to creep,
# a poof where a creep died — same wall-clock expiry discipline as beams
ZAP_ARC_S = 0.3
POOF_S = 0.6

TARGET_EVERY = 3.0  # per-drone nearest-creep hint

# ------------------------------------------------------------------- roles
# Repair: every chewed cell becomes a ghost and a callout to nearby carriers;
# a tile back on it scores. Scout: hover a gate and you hear what comes
# through it, and the room hears you.
REPAIR_TTL_S = 90.0  # a repair nobody takes stops being announced
REPAIR_CALL_RADIUS = 40.0  # m: carriers this close hear "repair at"
REPAIR_POINTS = 1
SPOT_RADIUS = 10.0  # m of a gate
SPOT_DWELL = 2.0  # s hovering it to become its spotter
SPOT_FEED_EVERY = 10.0  # s per gate: the relay line on the projector
FERRY_FEED_EVERY = 5  # pickups per "ferried" feed row
BUILD_FEED_EVERY = 5  # placements per "built" feed row
ANNOUNCE_EVERY = 30.0
BUILD_HINT_EVERY = 20.0  # 'build a tower at …' while the room has time to build
BUILD_SITE_STEPS = 8  # cells before the Keep along the lane: ~40 m out, where the
# zappers camping the gates have not already emptied the lane (tower range 16)
FERRY = FerryTexts("steel", "GAME: steel lost, grab another",
                   "GAME: got steel, wall or tower it",
                   "GAME: hands full, wall or tower it")
FERRY_CLAY = FerryTexts("clay", "GAME: clay lost, grab another",
                        "GAME: got clay, cheap walls, chewed 3x faster",
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
    towers' worth), a lone rehearsal drone 8 (7 during grace, wave 0)."""
    return QUARRY_STOCK_BASE + QUARRY_STOCK_PER_PILOT * pilots + QUARRY_STOCK_PER_WAVE * wave


# --------------------------------------------------------------------- shop
# Wallets buy *personal* tiers — the pot is the team's, the spending is yours.
# Prices assume a pilot earns about the wave's kill count per wave (10-20):
# one zap tier by wave 2, the ladder's top rungs only for a long round.
SHOP: Final[dict[str, tuple[int, ...]]] = {
    "zap": (20, 40, 80),  # reach + faster dwell
    "speed": (30, 60),  # horizontal and climb caps
    "tower": (40, 80),  # range + rate of every tower you built
    "colour": (10,),  # cosmetics: repeatable, one price
    "outline": (10,),
}
COSMETICS = ("colour", "outline")
ZAP_RADIUS_PER_TIER = 1.0  # 4 -> 5 -> 6 -> 7 m
ZAP_DWELL_PER_TIER = 0.25  # 1.5 -> 1.25 -> 1.0 -> 0.75 s
SPEED_SCALE_PER_TIER = 0.25  # 10 -> 12.5 -> 15 m/s (climb scales the same)
TOWER_RANGE_PER_TIER = 4.0  # 16 -> 20 -> 24 m
TOWER_COOLDOWN_PER_TIER = 0.5  # 2.0 -> 1.5 -> 1.0 s
TOWER_COOLDOWN_MIN = 1.0  # the floor, so stacking bonuses never makes a turret
_ROMAN = ("0", "I", "II", "III")
_HEX_RE = re.compile(r"#[0-9a-f]{6}")
SAY_MENU = "GAME: say shop, wallet or buy <item>"


@dataclass
class Upgrades:
    """One pilot's purchases this round: tiers and two cosmetics."""

    zap: int = 0
    speed: int = 0
    tower: int = 0
    colour: str | None = None
    outline: str | None = None

    def as_dict(self) -> dict:
        return {"zap": self.zap, "speed": self.speed, "tower": self.tower,
                "colour": self.colour, "outline": self.outline}


_NO_UPGRADES = Upgrades()  # the read-only default for a pilot who bought nothing

_HINTS = ("GAME: stack 3 steel = watchtower",
          "GAME: say shop to spend your coins",
          "GAME: bored? say quest for a challenge",
          "GAME: hover low on a creep to zap it",
          "GAME: 2-high walls turn creeps aside",
          "GAME: clay walls: cheap, chewed 3x faster",
          "GAME: ring a tower with 6 steel = long range",
          "GAME: clay-steel-clay line = beacon, lures creeps",
          "GAME: bell: 6 clay ring + 3 clay, hover to ring",
          "GAME: drop a tile on a creep to squish it",
          "GAME: clean wave +10, each leak costs -1",
          "GAME: towers shoot 16 m, build by the path")


@dataclass
class PilotStats:
    """What one pilot did this round — the 'who did what' behind the points."""

    zapped: int = 0
    squished: int = 0
    towers: int = 0
    ferried: int = 0  # tiles picked up
    placed: int = 0  # tiles put down
    repaired: int = 0  # …onto a chewed cell
    spots: int = 0  # gate reports relayed to the room

    def as_dict(self) -> dict:
        return {"zapped": self.zapped, "squished": self.squished, "towers": self.towers,
                "ferried": self.ferried, "placed": self.placed, "repaired": self.repaired,
                "spots": self.spots}

    @property
    def detail(self) -> str:
        """The board's compact column: z12 t2 f8 b6 r3 s1, empties dropped."""
        parts = [(k, v) for k, v in (("z", self.zapped + self.squished), ("t", self.towers),
                                     ("f", self.ferried), ("b", self.placed),
                                     ("r", self.repaired), ("s", self.spots)) if v]
        return " ".join(f"{k}{v}" for k, v in parts)


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
    quests_solved: int = 0
    quests_missed: int = 0  # room quests nobody solved
    ring_towers: int = 0
    bells: int = 0  # rung
    first_tower_s: float | None = None  # seconds into the round
    coins_spent: int = 0  # at the shop
    pilots: dict[str, PilotStats] = field(default_factory=dict)  # student_id -> theirs

    def pilot(self, student_id: str | None) -> PilotStats:
        return self.pilots.setdefault(student_id or "?", PilotStats())

    @property
    def kills(self) -> int:
        return self.zapped + self.squished + self.shot

    def as_dict(self) -> dict:
        return {"zapped": self.zapped, "squished": self.squished, "shot": self.shot,
                "kills": self.kills, "leaks": self.leaks, "towers": self.towers,
                "keep_hits": self.keep_hits, "keep_falls": self.keep_falls,
                "best_wave": self.best_wave, "quests_solved": self.quests_solved,
                "quests_missed": self.quests_missed, "ring_towers": self.ring_towers,
                "bells": self.bells, "first_tower_s": self.first_tower_s,
                "coins_spent": self.coins_spent,
                "pilots": {sid: p.as_dict() for sid, p in self.pilots.items()}}


@dataclass
class Tower:
    """A completed watchtower: who raised it (kills credit them), its cooldown."""

    builder: str | None
    last_shot: float = -math.inf  # loaded and ready
    kills: int = 0
    ring: bool = False  # ringed with 6 steel: RING_RANGE / RING_COOLDOWN


@dataclass
class Beacon:
    """A lure: its own flow field; creeps in range walk to it and chew it."""

    builder: str | None
    cells: tuple[Axial, ...]  # steel anchor, then the two clay
    flow: FlowField
    chew_acc: float = 0.0
    lured: int = 0  # this tick, for the viewer


@dataclass
class Bell:
    builder: str | None
    cells: tuple[Axial, ...]
    dwell: DwellTracker


@dataclass
class Repair:
    """A chewed cell: what stood there, how high it was, since when."""

    material: str
    need: int
    since: float


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
    # the bonus lane's creep: only through gate S, only while the triangle holds
    "raider": CreepKind("raider", hp=2, speed_mult=1.2, bounty=6, chew_rate=1.0,
                        keep_cost=1, from_wave=1),
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
        self.pit = TileSource("clay_pit", *PIT, material="clay")  # infinite
        self.tracker = PlaceTracker(self.tm, self.carry)
        self.blueprints = BlueprintTracker([TOWER_BP])
        # one tracker per structure: the watchtower claims its centre, and the
        # ring must be allowed to include that very cell
        self.ring_bps = BlueprintTracker([RING_BP])
        self.beacon_bps = BlueprintTracker([BEACON_BP])
        self.bell_bps = BlueprintTracker([BELL_BP])
        self.towers: dict[Axial, Tower] = {}
        self.beacons: dict[Axial, Beacon] = {}
        self.bells: dict[Axial, Bell] = {}
        self.lured: set[int] = set()  # creep uids walking to a beacon this tick
        self.freeze_s = 0.0  # the bell's gift: creeps stand still
        self.form_acc = 0.0  # s the triangle has held over gate S
        self.form_told: set[str] = set()  # who heard "formation! hold" this attempt
        self.bonus_open = False
        self.bonus_pending = 0  # raiders still to spawn while it holds
        self.bonus_wave = 0  # the wave whose opening was used
        self.bonus_timer = 0.0
        self.repairs: dict[Axial, Repair] = {}  # chewed cells worth rebuilding
        self.spot_dwell = [DwellTracker(SPOT_RADIUS, float("inf"), SPOT_DWELL) for _ in GATES]
        self.spotters: dict[int, str] = {}  # gate index -> drone id
        self.last_spot_feed: dict[int, float] = {}  # gate index -> when the room last heard
        self.last_repair_call = 0.0
        self.creeps: dict[int, GroundUnit] = {}
        self.zap: dict[int, DwellTracker] = {}  # creep uid -> hover dwell
        self.zap_ready: dict[str, float] = {}  # drone id -> when its next zap may land
        self.zap_high: dict[int, DwellTracker] = {}  # creep uid -> too-high dwell (a hint)
        # siege's own dice: reseeded from the engine's on every round, so the
        # gate sequence differs between rounds yet stays reproducible per seed
        self.rng = random.Random(0)
        self.round = 0
        self.round_started = 0.0  # world.now at setup: rounds.jsonl's duration
        self.stats = SiegeStats()
        self.flow = path.flood(self.tm, KEEP_CELL, climb=CLIMB)
        self._flow_version = self.tm.version
        # the empty-map field: what a pilot can model without seeing the tiles
        self.flow0 = path.flood(TileMap(), KEEP_CELL, climb=CLIMB)
        self.keep_cell = KEEP_CELL
        self.chew_s = CHEW_S
        self.quests = QuestBoard()
        self.buff: Buff | None = None  # this wave's penalty for a missed room quest
        self.wave_size = 0  # creeps announced for the wave (the boss aside)
        self.heard_wave: set[str] = set()  # drones that heard this wave's gate lines
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
        self.pit_hints = SourceHints(self.carry, FERRY_CLAY.full_say, throttle=self.hints.throttle)
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
        self.upgrades: dict[str, Upgrades] = {}  # student_id -> what they bought

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        self.tm.set_keep_out([KEEP, QUARRY, PIT, BONUS_GATE, *GATES])  # pads: engine-protected
        self.round_started = world.now
        self.rng = random.Random(world.rng.getrandbits(32))
        # the quest dice come AFTER siege's own draw: gate sequences per seed
        # stay what they were before quests existed (a test pins them)
        self.quests.clear(random.Random(world.rng.getrandbits(32)))
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
            # a fresh link means a fresh (or respawned) drone: stock caps
            world.set_speed(drone.id, self._speed_scale(drone.student_id))
        elif kind in ("crashed", "disconnected"):
            q = self.quests.drop(drone.id)
            if q is not None and kind == "crashed":
                world.send_text(drone.id, f"GAME: {q.tag} off: crashed")

    def on_text(self, world: WorldAPI, drone: DroneView, text: str) -> None:
        """The command surface: what `drone.say(...)` understands."""
        cmd = " ".join(text.lower().split())
        if cmd == "wallet":
            coins = self.wallets.get(drone.student_id, 0)
            world.send_text(drone.id, f"GAME: wallet {coins} coins")
        elif cmd == "shop":
            world.send_text(drone.id, "GAME: shop: zap 20/40/80, speed 30/60")
            world.send_text(drone.id, "GAME: shop: tower 40/80, colour 10, outline 10")
            world.send_text(drone.id, "GAME: buy colour #RRGGBB, buy outline #RRGGBB")
        elif cmd.startswith("buy "):
            self._buy(world, drone, cmd[4:].split())
        elif cmd == "quest":
            if self.quests.enrol(drone):
                world.send_text(drone.id, "GAME: quests on, first one soon")
            else:
                world.send_text(drone.id, "GAME: quests already on")
        elif cmd == "quest off":
            self.quests.unenrol(drone)
            world.send_text(drone.id, "GAME: quests off")
        else:
            world.send_text(drone.id, SAY_MENU)

    def pilot(self, student_id: str) -> dict:
        mine = self.stats.pilots.get(student_id)
        return {"wallet": self.wallets.get(student_id, 0),
                **self._up(student_id).as_dict(),
                "detail": mine.detail if mine is not None else ""}

    # ------------------------------------------------------------------ shop

    def _up(self, student_id: str | None) -> Upgrades:
        return self.upgrades.get(student_id or "", _NO_UPGRADES)

    def _zap_radius(self, d: DroneView) -> float:
        return ZAP_RADIUS + ZAP_RADIUS_PER_TIER * self._up(d.student_id).zap

    def _zap_dwell(self, d: DroneView) -> float:
        return ZAP_DWELL - ZAP_DWELL_PER_TIER * self._up(d.student_id).zap

    def _speed_scale(self, student_id: str) -> float:
        return 1.0 + SPEED_SCALE_PER_TIER * self._up(student_id).speed

    def _tower_stats(self, tower: Tower) -> tuple[float, float, int]:
        """(range, cooldown, tier) for a tower: the ring sets the base, the
        builder's tier adds range; the ring's reload is already the fast one
        (tiers on top of it would make one tower a wave-killer)."""
        tier = self._up(tower.builder).tower
        if tower.ring:
            return RING_RANGE + TOWER_RANGE_PER_TIER * tier, RING_COOLDOWN, tier
        return (TOWER_RANGE + TOWER_RANGE_PER_TIER * tier,
                max(TOWER_COOLDOWN_MIN, TOWER_COOLDOWN - TOWER_COOLDOWN_PER_TIER * tier),
                tier)

    def _buy(self, world: WorldAPI, drone: DroneView, words: list[str]) -> None:
        item = words[0] if words else ""
        if item == "color":
            item = "colour"
        if item not in SHOP:
            world.send_text(drone.id, "GAME: no such item, say shop")
            return
        sid = drone.student_id
        wallet = self.wallets.get(sid, 0)
        up = self.upgrades.setdefault(sid, Upgrades())
        if item in COSMETICS:
            value = words[1] if len(words) > 1 else ""
            if not _HEX_RE.fullmatch(value):
                world.send_text(drone.id, "GAME: bad colour, use #RRGGBB")
                return
            price = SHOP[item][0]
            if wallet < price:
                world.send_text(drone.id, f"GAME: need {price} coins, have {wallet}")
                return
            setattr(up, item, value)
            bought, level = value, value
        else:
            tier = getattr(up, item)
            if tier >= len(SHOP[item]):
                world.send_text(drone.id, f"GAME: {item} maxed at {_ROMAN[tier]}")
                return
            price = SHOP[item][tier]
            if wallet < price:
                world.send_text(drone.id, f"GAME: need {price} coins, have {wallet}")
                return
            setattr(up, item, tier + 1)
            bought, level = _ROMAN[tier + 1], tier + 1
            if item == "speed":
                world.set_speed(drone.id, self._speed_scale(sid))
        self.wallets[sid] = wallet - price
        self.stats.coins_spent += price
        # widest: "GAME: bought outline #ff8800 (9999 left)" = 41
        world.send_text(drone.id, f"GAME: bought {item} {bought} ({wallet - price} left)")
        world.emit_event("upgrade", f"{drone.name} bought {item} {bought}", student_id=sid,
                         data={"item": item, "level": level, "price": price})

    def _brief(self, world: WorldAPI, drone: DroneView) -> None:
        """What a newcomer needs, and nothing that already happened: the
        landmarks and where the game is right now."""
        self.last_brief = world.now
        world.send_text(drone.id, f"GAME: keep at {fmt_world(*KEEP)}, protect it!")
        world.send_text(drone.id, f"GAME: quarry at {fmt_world(*QUARRY)}")
        world.send_text(drone.id, f"GAME: clay pit at {fmt_world(*PIT)}")
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
            for gate in self.gates[1:]:  # the other lanes: where to expect creeps
                world.send_text(drone.id, f"GAME: wave {self.wave} also at {fmt_world(*gate)}")
            # not added to heard_wave: the brief says what is LEFT, not the
            # wave's size, so the count quests would be unfair to a late joiner

    def reset(self, world: WorldAPI) -> None:
        self._round_end(world)
        self.tm.clear()
        self.carry.clear()
        self.tracker.reset()
        self.blueprints.reset()
        self.ring_bps.reset()
        self.beacon_bps.reset()
        self.bell_bps.reset()
        self.quarry.dwell.clear()
        self.pit.dwell.clear()
        self.towers.clear()
        self.beacons.clear()
        self.bells.clear()
        self.lured.clear()
        self.freeze_s = 0.0
        self.repairs.clear()
        self.form_acc, self.bonus_open, self.bonus_pending = 0.0, False, 0
        self.bonus_wave, self.bonus_timer = 0, 0.0
        self.form_told.clear()
        for dw in self.spot_dwell:
            dw.clear()
        self.spotters.clear()
        self.last_spot_feed.clear()
        self.last_repair_call = 0.0
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
        self.pit_hints.clear()
        self.place_hints.clear()
        self.empty_hint.clear()
        self.pool = 0
        self.wallets.clear()
        self.upgrades.clear()
        for d in world.drones():  # the sim's World.reset does this too; missions
            world.set_speed(d.id, 1.0)  # must not depend on the order of the two
        self.buff = None
        self.wave_size = 0
        self.heard_wave.clear()
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
            "quests": self.quests.hud(self.stats.quests_solved, self.stats.quests_missed),
            "frozen_s": max(0, math.ceil(self.freeze_s)),
            "gate_s": "open" if self.bonus_open else "sealed",
        }

    # ------------------------------------------------------------------ tick

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = list(world.drones())

        for d, _source in tick_ferry(world, drones, self.carry, [self.quarry, self.pit], dt,
                                     FERRY, texts_by_material={"steel": FERRY, "clay": FERRY_CLAY}):
            mine = self.stats.pilot(d.student_id)
            mine.ferried += 1
            if mine.ferried % FERRY_FEED_EVERY == 0:
                world.emit_event("ferried", f"{d.name} ferried {mine.ferried} tiles",
                                 student_id=d.student_id)
        self.hints.tick(world, drones, *QUARRY, dt)
        self.pit_hints.tick(world, drones, *PIT, dt)
        self.empty_hint.tick(world, drones, *QUARRY, dt)
        placed, refused = self.tracker.tick(drones, dt)
        self.place_hints.tick(world, drones, dt)
        for p in placed:
            self._squish(world, p)
            self._count_placement(world, p)
            if not self._raise_structure(world, p):
                world.send_text(p.drone.id, f"GAME: placed! tile at {fmt_cell(p.cell)}")
        for d, _cell in refused:
            world.send_text(d.id, "GAME: can't build there")

        if self.tm.version != self._flow_version:
            self._check_towers(world)
            self._check_beacons(world)
            self._check_bells(world)
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
                self._report_spawn(world)
        self._hold_the_south(world, drones, dt)

        self._ring_bells(world, drones, dt)
        if self.freeze_s > 0:
            self.freeze_s -= dt  # the bell: nobody walks, nobody chews
        else:
            self._march(world, dt)

        self._fire_towers(world)
        self._zap(world, drones, dt)
        self._wave_machine(world, dt)
        for done in self.quests.tick(world, self, drones, dt):
            self._quest_resolved(world, done)

        if (world.now - self.last_announce > ANNOUNCE_EVERY
                and world.now - self.last_brief > 2.0):  # a newcomer just heard it
            self.last_announce = world.now
            self._announce(world)
        if self.creeps and world.now - self.last_target > TARGET_EVERY:
            self.last_target = world.now
            self._call_targets(world, drones)
        self._watch_gates(world, drones, dt)
        if self.repairs and world.now - self.last_repair_call > TARGET_EVERY:
            self.last_repair_call = world.now
            self._call_repairs(world, drones)
        if (self.state in ("grace", "build")
                and world.now - self.last_build_hint > BUILD_HINT_EVERY):
            self.last_build_hint = world.now
            self._call_build_site(world)

    def _march(self, world: WorldAPI, dt: float) -> None:
        """Creeps walk: the lured ones to their beacon, the rest to the Keep.
        Two calls to the walker, two meanings of 'arrived' — a beacon's
        arrivals chew the beacon, the Keep's are leaks."""
        self.lured.clear()
        by_beacon: dict[Axial, list[GroundUnit]] = {a: [] for a in self.beacons}
        to_keep: list[GroundUnit] = []
        for uid, u in self.creeps.items():
            near = min(((math.hypot(u.n - hex.axial_to_world(a)[0],
                                    u.e - hex.axial_to_world(a)[1]), a)
                        for a in self.beacons), default=None)
            if near is not None and near[0] <= BEACON_RADIUS:
                by_beacon[near[1]].append(u)
                self.lured.add(uid)
            else:
                to_keep.append(u)
        chews: list[Axial] = []
        result = step_units(to_keep, self.tm, self.flow, dt, CHEW_S, chew_factor=CHEW_FACTOR)
        for u in result.arrived:
            self.leaks += 1
            self._kill(world, u.uid, "leak")
            for _ in range(u.keep_cost):
                self._keep_hit(world)
        chews += [cell for _u, cell in result.chews]
        for anchor, units in by_beacon.items():
            beacon = self.beacons[anchor]
            lured = step_units(units, self.tm, beacon.flow, dt, CHEW_S, chew_factor=CHEW_FACTOR)
            beacon.lured = len(units)
            for u in lured.arrived:  # standing on the beacon: eating it
                beacon.chew_acc += dt * u.chew_rate
            chews += [cell for _u, cell in lured.chews]
            if beacon.chew_acc >= CHEW_S - _EPS:
                beacon.chew_acc = 0.0
                chews.append(anchor)
        for cell in chews:
            need = self.tm.height(cell)
            material = self.tm.remove_top(cell)
            if material is not None:  # widest: "GAME: steel chewed at N -97 E -97" = 34
                world.broadcast_text(f"GAME: {material} chewed at {fmt_cell(cell)}",
                                     severity=SEV_WARNING)
                if cell not in self.repairs:  # the first bite sets what "whole" was
                    self.repairs[cell] = Repair(material, need, world.now)

    # ------------------------------------------------------------ structures

    def _raise_structure(self, world: WorldAPI, p) -> bool:
        """A placement may complete a structure; say which. True if it did."""
        sid, name = p.drone.student_id, p.drone.name
        raised = False
        match = self.blueprints.check(self.tm, p.cell, extra_claimed=self._others(self.blueprints))
        if match is not None:
            self.towers[match.anchor] = Tower(builder=sid)
            self.stats.towers += 1
            self.stats.pilot(sid).towers += 1
            if self.stats.first_tower_s is None:
                self.stats.first_tower_s = round(world.now - self.round_started, 1)
            world.add_score(TOWER_POINTS, f"watchtower at {fmt_cell(match.anchor)}",
                            student_id=sid, feed=False)
            world.emit_event("tower_up", f"{name} raised a watchtower! +{TOWER_POINTS}",
                             student_id=sid, data={"points": TOWER_POINTS})
            # widest: "GAME: tower up at N -97 E -97! +15" = 36 — every script
            # learns where towers stand (the chokepoint answer wants it)
            world.broadcast_text(f"GAME: tower up at {fmt_cell(match.anchor)}! +{TOWER_POINTS}")
            raised = True
        ring = self.ring_bps.check(self.tm, p.cell, extra_claimed=self._others(self.ring_bps))
        if ring is not None and ring.anchor in self.towers:
            self.towers[ring.anchor].ring = True
            self.stats.ring_towers += 1
            world.add_score(RING_POINTS, f"ring tower at {fmt_cell(ring.anchor)}",
                            student_id=sid, feed=False)
            world.emit_event("ring_up", f"{name} ringed a tower: long range! +{RING_POINTS}",
                             student_id=sid, data={"points": RING_POINTS})
            # widest: "GAME: ring tower at N -97 E -97! +25" = 37
            world.broadcast_text(f"GAME: ring tower at {fmt_cell(ring.anchor)}! +{RING_POINTS}")
            raised = True
        elif ring is not None:  # a ring around a stack that is not a tower (cannot happen
            for cell in ring.cells:  # in practice: 3 steel on a cell IS a tower)
                self.ring_bps.claimed.discard(cell)
        if len(self.beacons) < BEACON_MAX:
            beacon = self.beacon_bps.check(self.tm, p.cell,
                                           extra_claimed=self._others(self.beacon_bps))
            if beacon is not None:
                self.beacons[beacon.anchor] = Beacon(
                    sid, beacon.cells, path.flood(self.tm, beacon.anchor, climb=CLIMB))
                world.emit_event("beacon_up", f"{name} lit a beacon at {fmt_cell(beacon.anchor)}",
                                 student_id=sid)
                # widest: "GAME: beacon up at N -97 E -97, creeps lured" = 45
                world.broadcast_text(f"GAME: beacon up at {fmt_cell(beacon.anchor)}, creeps lured")
                raised = True
        bell = self.bell_bps.check(self.tm, p.cell, extra_claimed=self._others(self.bell_bps))
        if bell is not None:
            top = self.tm.top_alt(bell.anchor)
            dwell = DwellTracker(BELL_RADIUS, top + BELL_ALT_ABOVE, BELL_DWELL_S)
            self.bells[bell.anchor] = Bell(sid, bell.cells, dwell)
            world.emit_event("bell_up", f"{name} built a bell at {fmt_cell(bell.anchor)}",
                             student_id=sid)
            # widest: "GAME: bell up at N -97 E -97, hover 8 m to ring" = 47
            world.broadcast_text(
                f"GAME: bell up at {fmt_cell(bell.anchor)}, hover {round(top + 2)} m to ring")
            raised = True
        return raised

    def _hold_the_south(self, world: WorldAPI, drones: list[DroneView], dt: float) -> None:
        """The sealed gate: three drones in a triangle over it for FORM_HOLD_S
        open it; raiders pour while the triangle holds (one opening a wave);
        the formation breaking seals it and drops the rest of the lane."""
        trio = (triangle(drones, *BONUS_GATE, FORM_RADIUS, FORM_MIN, FORM_MAX, FORM_MIN_ANGLE)
                if self.state == "active" else None)
        if trio is None:
            if self.bonus_open:
                self.bonus_open, self.bonus_pending = False, 0
                world.emit_event("gate_sealed", "the formation broke — gate S is sealed")
                world.broadcast_text("GAME: formation broken, gate S sealed", severity=SEV_WARNING)
            self.form_acc = 0.0
            self.form_told.clear()
            return
        if self.bonus_open:
            self.bonus_timer -= dt
            if self.bonus_pending > 0 and self.bonus_timer <= 0:
                self.bonus_timer += SPAWN_GAP
                self._spawn_raider()
            return
        if self.bonus_wave == self.wave:
            return  # this wave's opening is spent; hold all you like
        for d in trio:
            if d.id not in self.form_told:
                self.form_told.add(d.id)
                world.send_text(d.id,
                                f"GAME: formation! hold {round(FORM_HOLD_S)} s to open gate S")
        self.form_acc += dt
        if self.form_acc >= FORM_HOLD_S - _EPS:
            self.bonus_open, self.bonus_pending, self.bonus_wave = True, BONUS_LANE_SIZE, self.wave
            self.bonus_timer = 0.0
            world.emit_event("gate_open", f"gate S is open: {BONUS_LANE_SIZE} raiders pay the pool",
                             data={"raiders": BONUS_LANE_SIZE})
            world.broadcast_text("GAME: south gate open! raiders pay the pool")

    def _spawn_raider(self) -> None:
        self._uid += 1
        self.bonus_pending -= 1
        kind = KINDS["raider"]
        n, e = BONUS_GATE
        self.creeps[self._uid] = GroundUnit(
            uid=self._uid, n=n, e=e, speed=_wave_speed(self.wave) * kind.speed_mult,
            kind=kind.name, hp=kind.hp, max_hp=kind.hp, bounty=kind.bounty,
            keep_cost=kind.keep_cost, chew_rate=kind.chew_rate, gate=-1)

    def _count_placement(self, world: WorldAPI, p) -> None:
        mine = self.stats.pilot(p.drone.student_id)
        mine.placed += 1
        if mine.placed % BUILD_FEED_EVERY == 0:
            world.emit_event("built", f"{p.drone.name} placed {mine.placed} tiles",
                             student_id=p.drone.student_id)
        rep = self.repairs.get(p.cell)
        if rep is None:
            return
        if self.tm.height(p.cell) >= rep.need:  # whole again
            del self.repairs[p.cell]
        mine.repaired += 1
        world.add_score(REPAIR_POINTS, f"{p.drone.name} repaired {fmt_cell(p.cell)}",
                        student_id=p.drone.student_id, feed=False)
        world.emit_event("repaired", f"{p.drone.name} repaired the wall at {fmt_cell(p.cell)}"
                         f" +{REPAIR_POINTS}", student_id=p.drone.student_id,
                         data={"points": REPAIR_POINTS})
        # widest: "GAME: repaired! N -97 E -97 whole again +1" = 42
        world.send_text(p.drone.id, f"GAME: repaired! {fmt_cell(p.cell)} "
                        + ("whole again" if p.cell not in self.repairs else "one more")
                        + f" +{REPAIR_POINTS}")

    def _call_repairs(self, world: WorldAPI, drones: list[DroneView]) -> None:
        """Every TARGET_EVERY: the nearest chewed cell to each carrier within
        reach, with the altitude that places. Stale repairs age out."""
        for cell, rep in list(self.repairs.items()):
            if world.now - rep.since > REPAIR_TTL_S or self.tm.height(cell) >= rep.need:
                del self.repairs[cell]
        if not self.repairs:
            return
        for d in drones:
            if not d.connected or not d.armed or d.crashed:
                continue
            material = self.carry.item(d.id)
            if material is None:
                continue
            best = min(((math.hypot(d.n - hex.axial_to_world(c)[0],
                                    d.e - hex.axial_to_world(c)[1]), c)
                        for c, r in self.repairs.items() if r.material == material),
                       default=None)
            if best is None or best[0] > REPAIR_CALL_RADIUS:
                continue
            cell = best[1]  # widest: "GAME: repair at N -97 E -97 hover 10" = 37
            world.send_text(d.id, f"GAME: repair at {fmt_cell(cell)} hover "
                            f"{hover_alt_hint(self.tm, cell)}")

    def _watch_gates(self, world: WorldAPI, drones: list[DroneView], dt: float) -> None:
        """A drone that hovers a gate for SPOT_DWELL becomes its spotter, and
        stays it while it stays near; leaving (or crashing) hands the post
        back."""
        by_id = {d.id: d for d in drones}
        for i, gate in enumerate(GATES):
            current = self.spotters.get(i)
            if current is not None:
                d = by_id.get(current)
                if (d is None or not d.armed or d.crashed or not d.connected
                        or math.hypot(d.n - gate[0], d.e - gate[1]) > SPOT_RADIUS):
                    del self.spotters[i]
                    if d is not None and d.connected:
                        world.send_text(d.id, f"GAME: gate {GATE_LABELS[i]} unwatched")
                continue
            taken = set(self.spotters.values())

            def free(d: DroneView, t: frozenset[str] = frozenset(taken)) -> bool:
                return d.id not in t  # one post per drone

            winner = self.spot_dwell[i].update(drones, gate[0], gate[1], dt, eligible=free)
            if winner is not None:
                self.spotters[i] = winner.id
                world.send_text(winner.id, f"GAME: you spot gate {GATE_LABELS[i]}")
                world.emit_event("spotter", f"{winner.name} is watching gate {GATE_LABELS[i]}",
                                 student_id=winner.student_id)

    def _report_spawn(self, world: WorldAPI) -> None:
        """The gate's spotter hears what is through it now (kind counts of
        the creeps alive that came from that gate); the room hears the
        spotter, throttled."""
        i = self._spawned_at
        drone_id = self.spotters.get(i)
        if drone_id is None or i < 0:
            return
        counts: dict[str, int] = {}
        for u in self.creeps.values():
            if u.gate == i:
                counts[u.kind] = counts.get(u.kind, 0) + 1
        parts = [f"{counts[k]} {k}" for k in KINDS if k in counts and k != "champion"]
        boss = "champion" in counts

        def wording(kinds: list[str], with_boss: bool) -> str:
            return f"gate {GATE_LABELS[i]}: " + " ".join(kinds) + (" + boss" if with_boss else "")

        # widest full line: "GAME: gate N: 5 grunt 6 runner 6 brute 3 sapper" = 47;
        # with a boss behind that it would not fit — the boss goes first, then
        # the rarest kinds, so the line always tells the truth it has room for
        report = wording(parts, boss)
        if len(report) + 6 > 50:
            report = wording(parts, False)
        while len(report) + 6 > 50 and len(parts) > 1:
            parts = parts[:-1]
            report = wording(parts, False)
        world.send_text(drone_id, f"GAME: {report}")
        if world.now - self.last_spot_feed.get(i, -math.inf) >= SPOT_FEED_EVERY:
            self.last_spot_feed[i] = world.now
            d = next((d for d in world.drones() if d.id == drone_id), None)
            if d is not None:
                self.stats.pilot(d.student_id).spots += 1
                world.emit_event("spotted", f"{d.name} spots {report}", student_id=d.student_id)

    def _others(self, mine: BlueprintTracker) -> frozenset[Axial]:
        """Cells every OTHER tracker owns: a tile in one structure never
        completes another (the watchtower centre is the one exception the
        ring tracker needs, so the ring does not exclude the tower's claims)."""
        trackers = [self.blueprints, self.ring_bps, self.beacon_bps, self.bell_bps]
        out: set[Axial] = set()
        for t in trackers:
            if t is not mine and not (mine is self.ring_bps and t is self.blueprints):
                out |= t.claimed
        return frozenset(out)

    def _check_beacons(self, world: WorldAPI) -> None:
        gone = [a for a, b in self.beacons.items() if not self._standing(BEACON_BP, b.cells)]
        for anchor in gone:
            b = self.beacons.pop(anchor)
            for cell in b.cells:
                self.beacon_bps.claimed.discard(cell)
            world.emit_event("beacon_lost", f"the beacon at {fmt_cell(anchor)} was chewed down")
            world.broadcast_text(f"GAME: beacon chewed at {fmt_cell(anchor)}", severity=SEV_WARNING)

    def _check_bells(self, world: WorldAPI) -> None:
        for anchor in [a for a, b in self.bells.items() if not self._standing(BELL_BP, b.cells)]:
            b = self.bells.pop(anchor)
            for cell in b.cells:
                self.bell_bps.claimed.discard(cell)
            world.emit_event("bell_lost", f"the bell at {fmt_cell(anchor)} was chewed down")
            world.broadcast_text(f"GAME: bell chewed at {fmt_cell(anchor)}", severity=SEV_WARNING)

    def _standing(self, bp: Blueprint, cells: tuple[Axial, ...]) -> bool:
        """The matched cells still satisfy their requirements, in match order."""
        for req, cell in zip(bp.reqs, cells, strict=True):
            h = self.tm.height(cell)
            if h < req.height or self.tm.top(cell) != req.material:
                return False
            if req.max_height is not None and h > req.max_height:
                return False
        return True

    def _ring_bells(self, world: WorldAPI, drones: list[DroneView], dt: float) -> None:
        for anchor, bell in list(self.bells.items()):
            n, e = hex.axial_to_world(anchor)
            top = self.tm.top_alt(anchor)
            def above(d: DroneView, t: float = top) -> bool:
                return d.alt > t  # on top of the stack, not beside it

            winner = bell.dwell.update(drones, n, e, dt, eligible=above)
            if winner is None:
                continue
            del self.bells[anchor]
            for cell in bell.cells:
                while self.tm.remove_top(cell) is not None:
                    pass
                self.bell_bps.claimed.discard(cell)
            self.freeze_s = FREEZE_S
            self.stats.bells += 1
            self._fx(world, "bell_ring", n, e, top, BELL_RING_S)
            world.emit_event("bell_rung",
                             f"{winner.name} rang the bell — creeps frozen {round(FREEZE_S)} s!",
                             student_id=winner.student_id, data={"freeze_s": FREEZE_S})
            world.broadcast_text(f"GAME: bell rung! creeps frozen {round(FREEZE_S)} s")

    # ---------------------------------------------------------------- combat

    def _squish(self, world: WorldAPI, p) -> None:
        for uid, u in list(self.creeps.items()):
            if u.cell == p.cell:
                self._damage(world, uid, u.hp, "squish", p.drone)  # a tile is a tile

    def _fire_towers(self, world: WorldAPI) -> None:
        for cell in sorted(self.towers):
            tower = self.towers[cell]
            reach, cooldown, _tier = self._tower_stats(tower)
            if world.now - tower.last_shot < cooldown:
                continue
            tn, te = hex.axial_to_world(cell)
            target = min(
                ((math.hypot(u.n - tn, u.e - te), uid) for uid, u in self.creeps.items()),
                default=None)
            if target is None or target[0] > reach:
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
                uid, DwellTracker(ZAP_RADIUS, float("inf"), HINT_SUSTAIN,
                                  radius_of=self._zap_radius))

            spotting = frozenset(self.spotters.values())

            def too_high(d: DroneView, c: float = ceiling,
                         posts: frozenset[str] = spotting) -> bool:
                return d.alt > c and d.id not in posts  # a spotter parks high on purpose

            nag = high.update(drones, u.n, u.e, dt, eligible=too_high)
            if nag is not None and self.hints.throttle.ready(f"zap_high:{nag.id}", world.now):
                world.send_text(nag.id, f"GAME: drop under {round(ceiling)} m to zap")
            tracker = self.zap.setdefault(
                uid, DwellTracker(ZAP_RADIUS, 0.0, ZAP_DWELL,
                                  radius_of=self._zap_radius, dwell_of=self._zap_dwell))
            tracker.max_alt = ceiling
            winner = tracker.update(drones, u.n, u.e, dt)
            if winner is not None:
                # one zap per drone per dwell: a hover over a clump takes the
                # creeps one at a time (this one's dwell just restarted), so a
                # parked drone is not an area weapon and splitting up pays
                if world.now < self.zap_ready.get(winner.id, -math.inf):
                    continue
                self.zap_ready[winner.id] = world.now + self._zap_dwell(winner) - _EPS
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
        lured = uid in self.lured
        self._kill(world, uid, verb)
        self.pool += COINS_PER_KILL_EACH * self._seated(world)
        if drone is not None:
            if verb == "zap":
                self.stats.pilot(drone.student_id).zapped += 1
            elif verb == "squish":
                self.stats.pilot(drone.student_id).squished += 1
        if lured and verb != "leak":  # a kill in the beacon's kill zone pays extra
            self.pool += LURE_BONUS_EACH * self._seated(world)
        who = drone.student_id if drone is not None else student_id
        # the feed row names the pilot: "+2: Alice zapped a grunt" is the
        # 'that was me' moment for twenty people at once; tower shots stay quiet
        reason = (f"{drone.name} {_kill_reason(verb)} a {u.kind}" if drone is not None
                  else f"{u.kind} {_kill_reason(verb)}")
        if u.kind == "raider":  # the south lane pays the room, not the pilot
            who = None
            self.pool += RAIDER_POOL_EACH * self._seated(world)
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
        self.lured.discard(uid)
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
            if self.leaks == 0:
                world.broadcast_text(f"GAME: wave {self.wave} clear! +{bonus}")
            else:
                world.broadcast_text(
                    f"GAME: wave {self.wave} clear, {self.leaks} leaked +{bonus}")
            share = self._pay_wallets(world)  # after the clear line: cause, then coins
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
            self.state, self.timer = "build", BUILD_S
            self.buff = None  # a penalty lasts one wave
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
        self.wave_size = size
        self.heard_wave = {d.id for d in world.drones() if d.connected}
        self.buff = self.quests.wave_started(world, self)
        if self.buff is not None:  # widest: "GAME: wave 100 buffed: faster" = 29
            world.broadcast_text(f"GAME: wave {wave} buffed: {self.buff.text}",
                                 severity=SEV_WARNING)

    def _spawn_creep(self) -> None:
        self._uid += 1
        self.pending -= 1
        self._spawned_at = -1
        kind = KINDS[self.roster.pop(0) if self.roster else "grunt"]
        gate = self.gates[self._lane % len(self.gates)]
        n, e = gate
        self._lane += 1
        self._spawned_at = GATES.index(gate)
        hp, speed = kind.hp, _wave_speed(self.wave) * kind.speed_mult
        if self.buff is not None:  # the room's penalty for an unsolved room quest
            hp += BUFF_HP if self.buff.kind == "hp" else 0
            speed *= BUFF_SPEED if self.buff.kind == "speed" else 1.0
        self.creeps[self._uid] = GroundUnit(
            uid=self._uid, n=n, e=e, speed=speed,
            kind=kind.name, hp=hp, max_hp=hp, bounty=kind.bounty,
            keep_cost=kind.keep_cost, chew_rate=kind.chew_rate, gate=self._spawned_at)

    def _quest_resolved(self, world: WorldAPI, done: Resolved) -> None:
        """The mission's side of a quest ending: pay, post, count."""
        q = done.quest
        if done.kind != "solved":
            if q.room:
                self.stats.quests_missed += 1
            return
        assert done.drone is not None
        d = done.drone
        self.stats.quests_solved += 1
        each = ROOM_QUEST_POOL_EACH if q.room else QUEST_POOL_EACH
        coins = each * self._seated(world)
        self.pool += coins
        reason = f"{d.name} solved {q.tag} ({q.family})"
        if q.room:
            world.add_score(QUEST_POINTS, reason, student_id=d.student_id, feed=False)
            world.emit_event("quest_solved", f"{reason}! pool +{coins}",
                             student_id=d.student_id,
                             data={"points": QUEST_POINTS, "quest": q.qid,
                                   "family": q.family, "pool": coins})
            for other in world.drones():
                if other.id != d.id:
                    world.send_text(other.id, f"GAME: {q.tag} solved!")
        else:
            world.add_score(QUEST_POINTS, reason, student_id=d.student_id, feed=True)
        # widest: "GAME: room quest 99 solved! +5, pool +192" = 41
        world.send_text(d.id, f"GAME: {q.tag} solved! +{QUEST_POINTS}, pool +{coins}")

    def _check_towers(self, world: WorldAPI) -> None:
        for cell in [c for c in self.towers if self.tm.height(c) < TOWER_HEIGHT]:
            tower = self.towers.pop(cell)
            self.blueprints.claimed.discard(cell)  # chewed down: rebuildable
            if tower.ring:
                self._drop_ring(cell)
            world.emit_event("tower_down", f"watchtower lost at {fmt_cell(cell)}")
            world.broadcast_text(f"GAME: tower down at {fmt_cell(cell)}",
                                 severity=SEV_WARNING)
        for cell, tower in self.towers.items():
            if tower.ring and match_at(self.tm, RING_BP, cell) is None:
                tower.ring = False
                self._drop_ring(cell)
                world.emit_event("ring_lost", f"the ring at {fmt_cell(cell)} is broken")
                # widest: "GAME: ring lost at N -97 E -97, watchtower again" = 48
                world.broadcast_text(f"GAME: ring lost at {fmt_cell(cell)}, watchtower again",
                                     severity=SEV_WARNING)

    def _drop_ring(self, centre: Axial) -> None:
        """Release a ring's claims (the centre stays the watchtower's)."""
        for cell in hex.ring(centre, 1):
            self.ring_bps.claimed.discard(cell)
        self.ring_bps.claimed.discard(centre)

    def _reflood(self) -> None:
        self.flow = path.flood(self.tm, KEEP_CELL, climb=CLIMB)
        for anchor, beacon in self.beacons.items():
            beacon.flow = path.flood(self.tm, anchor, climb=CLIMB)
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
            data={**st.as_dict(), "score": world.score, "round": self.round + 1,
                  "duration_s": round(world.now - self.round_started),
                  "pool": self.pool, "wallets": sum(self.wallets.values())})
        world.broadcast_text(f"GAME: round over! wave {st.best_wave}, {st.kills} kills")
        self.last_round = {"round": self.round + 1, "wave": st.best_wave,
                           "kills": st.kills, "score": world.score}

    # ---------------------------------------------------------- announcements

    def _announce(self, world: WorldAPI) -> None:
        world.broadcast_text(f"GAME: keep at {fmt_world(*KEEP)}, protect it!")
        world.broadcast_text(f"GAME: quarry at {fmt_world(*QUARRY)}")
        world.broadcast_text(f"GAME: clay pit at {fmt_world(*PIT)}")
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
               self.quarry.entity(), self.pit.entity()]
        for i, (gate, label) in enumerate(zip(GATES, GATE_LABELS, strict=True)):
            active = self.state == "active" and gate in self.gates and self.pending > 0
            out.append(Entity(id=f"gate{i}", kind="gate", n=gate[0], e=gate[1], alt=0.0,
                              data={"label": label, "active": active}))
        out.append(Entity(id="gate3", kind="gate", n=BONUS_GATE[0], e=BONUS_GATE[1], alt=0.0,
                          data={"label": "S", "active": self.bonus_open and self.bonus_pending > 0,
                                "sealed": not self.bonus_open,
                                "hold": round(min(1.0, self.form_acc / FORM_HOLD_S), 2)}))
        frozen = self.freeze_s > 0
        for uid, u in self.creeps.items():
            out.append(Entity(id=f"creep{uid}", kind="troop", n=u.n, e=u.e, alt=u.alt,
                              data={"dir": u.heading, "chewing": u.chewing,
                                    "kind": u.kind, "hp": u.hp, "max": u.max_hp,
                                    "frozen": frozen, "lured": uid in self.lured}))
        for cell, rep in self.repairs.items():
            n, e = hex.axial_to_world(cell)
            out.append(Entity(id=f"repair_{cell[0]}_{cell[1]}", kind="ghost_tile", n=n, e=e,
                              alt=self.tm.top_alt(cell),
                              data={"material": rep.material, "need": rep.need,
                                    "have": self.tm.height(cell), "size": hex.HEX_SIZE}))
        for anchor, beacon in self.beacons.items():
            n, e = hex.axial_to_world(anchor)
            out.append(Entity(id=f"beacon_{anchor[0]}_{anchor[1]}", kind="beacon", n=n, e=e,
                              alt=self.tm.top_alt(anchor),
                              data={"radius": BEACON_RADIUS, "lured": beacon.lured,
                                    "chew": round(beacon.chew_acc / CHEW_S, 2)}))
        for anchor, bell in self.bells.items():
            n, e = hex.axial_to_world(anchor)
            charge = max(bell.dwell.acc.values(), default=0.0) / BELL_DWELL_S
            out.append(Entity(id=f"bell_{anchor[0]}_{anchor[1]}", kind="bell", n=n, e=e,
                              alt=self.tm.top_alt(anchor),
                              data={"hover": round(self.tm.top_alt(anchor) + 2),
                                    "charge": round(min(1.0, charge), 2)}))
        # the suggested site, as a ghost the instructor can point at, while
        # there is time to build and until a tower stands there
        if (self.state in ("grace", "build") and self.site is not None
                and self.tm.height(self.site) < TOWER_HEIGHT):
            n, e = hex.axial_to_world(self.site)
            out.append(Entity(id="site", kind="ghost_tile", n=n, e=e,
                              alt=self.tm.top_alt(self.site),
                              data={"material": "steel", "need": TOWER_HEIGHT,
                                    "have": self.tm.height(self.site), "size": hex.HEX_SIZE}))
        for cell, tower in self.towers.items():
            n, e = hex.axial_to_world(cell)
            reach, _cooldown, tier = self._tower_stats(tower)
            out.append(Entity(id=f"tower_{cell[0]}_{cell[1]}", kind="tower",
                              n=n, e=e, alt=self.tm.top_alt(cell),
                              data={"range": reach, "tier": tier, "ring": tower.ring}))
        for mark_id, cell, data in room_marks(self.quests.room):
            n, e = hex.axial_to_world(cell)
            out.append(Entity(id=mark_id, kind="quest_mark", n=n, e=e, alt=0.0, data=data))
        for beam_id, _expiry, (n, e, alt), (tn, te, talt) in self.beams:
            out.append(Entity(id=beam_id, kind="beam", n=n, e=e, alt=alt,
                              data={"tn": tn, "te": te, "talt": talt}))
        for fx_id, _expiry, kind, (n, e, alt), data in self.fx:
            out.append(Entity(id=fx_id, kind=kind, n=n, e=e, alt=alt, data=data))
        out.extend(self.carry.entities(world.drones()))
        return out
