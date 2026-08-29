"""Quests: siege's advanced play — a programming challenge, never a reflex.

A quest is a small task the game states in GAME text and checks by watching
the drone fly: visit these cells in this order, be where that creep will be
in fifteen seconds, hover over the Keep at an altitude that equals a number
you have to compute. Three FAMILIES, each needing a different kind of code
(parse a list and sequence goto; model a creep's march; do geometry over
what the game announced), and every instance is drawn per pilot from the
live world, so two neighbours never share numbers — only code generalises.

Personal quests are opt-in (`say quest`): the unedited template's log pane
stays readable. A ROOM quest is broadcast to everyone at a wave start
whenever none is open (from wave 3); it runs its own 60 s clock, and if
nobody solves it in time the next wave comes buffed (the room-wide
penalty).

The board owns issue/check/expire and the quest-side texts; the mission
owns rewards (pool, points, events) — they arrive as `Resolved` records.
Every line here obeys the STATUSTEXT law (mission.py): "GAME: ", ≤ 50
chars, positions via fmt_cell/fmt_world, no floats — the widths are pinned
by tests at their widest (quest 99, N -97 E -97).
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..sim.backend import DroneView
from . import hex
from .building import DwellTracker, fmt_cell
from .hex import Axial
from .mission import WorldAPI, fmt_world
from .path import FlowField
from .tiles import TileMap
from .units import GroundUnit, step_units

# ------------------------------------------------------------------ knobs
QUEST_FROM_WAVE = 2  # personal quests start once the room has seen a wave
ROOM_QUEST_FROM_WAVE = 3
QUEST_FIRST_S = 5.0  # after `say quest`: something happens soon
QUEST_GAP_S = 20.0  # between one quest's end and the next
ISSUE_PER_TICK = 4  # 60 pilots spread over 1.5 s, then drift apart
ROOM_QUEST_S = 60.0  # or the next wave start, whichever first
QUEST_ID_MAX = 99  # two digits: the widest lines assume it

ROUTE_STOPS = {1: 3, 2: 4, 3: 5}
ROUTE_MPS = 6.0  # a comfortable cruise for the time limit (V_XY_MAX is 10)
ROUTE_SLACK_S = 4.0  # per stop: the turn, the settle
ROUTE_LIMIT = (30.0, 90.0)
ROUTE_TOUCH_M = 2.5
ROUTE_MIN_GAP_M = 20.0  # stops apart, and the first from the pilot
ROUTE_N_MIN = -70.0  # above the pad rows
ROUTE_ALTS = (12.0, 18.0, 25.0)  # the "at H m" variant (walls top out at 8)
ROUTE_ALT_TOL = 1.5
ROUTE_ANY_ORDER_RATIO = 1.5  # listed order must cost this much more than optimal
ROUTE_DRAWS = 10

PREDICT_T = {1: 8, 2: 12, 3: 15}  # seconds ahead
PREDICT_RADIUS = 6.0  # a hex pitch is 5.2 m: one cell of slack for a tie-break
PREDICT_STILL_S = 2.0  # parked, not chasing the callouts
PREDICT_STILL_V = 1.0  # m/s
PREDICT_MIN_MOVE = 8.0  # it must actually go somewhere
PREDICT_KINDS = {1: ("grunt",), 2: ("grunt", "runner", "brute", "sapper"),
                 3: ("runner", "brute")}

COMPUTE_S = 45.0
COMPUTE_RADIUS = 3.0  # over the Keep
COMPUTE_HOLD_S = 2.0
COMPUTE_TOL = 1.0  # m of altitude
ANSWER_RANGE = (3.0, 55.0)  # ALT_MAX is 60; below 3 the Keep's zap zone
COMPUTE_DIVISORS = (2, 3, 4, 5, 6)

QUEST_POINTS = 5  # personal, on the board — the named feed row
QUEST_POOL_EACH = 1  # pool += this x seated, a personal solve
ROOM_QUEST_POOL_EACH = 3  # …and a room solve
BUFF_HP = 1
BUFF_SPEED = 1.2

_EPS = 1e-9  # dt accumulates in floats; N*dt may land a hair over N*dt exactly

Family = Literal["route", "predict", "compute"]
FAMILIES: tuple[Family, ...] = ("route", "predict", "compute")
ROOM_FAMILIES: tuple[Family, ...] = ("route", "compute")


def tier_for(wave: int) -> int:
    """Difficulty bands follow the gates: 1 through wave 4, 2 to 7, 3 after."""
    return 1 if wave <= 4 else 2 if wave <= 7 else 3


class QuestCtx(Protocol):
    """What the board reads from the mission (siege passes itself)."""

    wave: int
    state: str
    tm: TileMap
    flow: FlowField  # the live field (walls and all)
    flow0: FlowField  # the empty-map field: what a pilot can model
    creeps: dict[int, GroundUnit]
    gates: tuple[tuple[float, float], ...]
    wave_size: int  # creeps announced for this wave (the boss aside)
    heard_wave: set[str]  # drone ids that heard this wave's gate lines
    chew_s: float
    keep_cell: Axial


@dataclass
class Buff:
    kind: Literal["hp", "speed"]

    @property
    def text(self) -> str:
        return "+1 hp" if self.kind == "hp" else "faster"


@dataclass
class Quest:
    qid: int
    family: Family
    variant: str
    tier: int
    room: bool
    owner: str | None  # drone id (personal) or None (room)
    left_s: float  # a dt countdown, like the siege clocks
    lines: list[str]  # the announcement, ready to send
    # route
    stops: list[Axial] = field(default_factory=list)
    order: list[int] = field(default_factory=list)  # required visiting order, or [] = any
    alt: float | None = None  # "at H m"
    progress: dict[str, list[int]] = field(default_factory=dict)  # drone -> stops touched
    # predict
    target: tuple[float, float] | None = None
    # compute
    answer: float | None = None
    hold: DwellTracker | None = None
    solved_by: str | None = None

    @property
    def tag(self) -> str:
        return f"room quest {self.qid}" if self.room else f"quest {self.qid}"


@dataclass
class Resolved:
    quest: Quest
    kind: Literal["solved", "expired", "dropped"]
    drone: DroneView | None = None


# ------------------------------------------------------------ predictions

def predict_position(unit: GroundUnit, tm: TileMap, flow: FlowField, seconds: float,
                     chew_s: float, dt: float = 0.1) -> tuple[float, float] | None:
    """Where the creep will stand after `seconds` on this field — a dry run
    of the real walker on a copy (units never mutate the map). None if it
    reaches the goal first."""
    u = dataclasses.replace(unit)
    for _ in range(round(seconds / dt)):
        if step_units([u], tm, flow, dt, chew_s).arrived:
            return None
    return u.n, u.e


# ----------------------------------------------------------------- drawing

def _cell_ok(tm: TileMap, cell: Axial, keep: Axial) -> bool:
    n, e = hex.axial_to_world(cell)
    return (tm.in_bounds(cell) and n >= ROUTE_N_MIN and abs(n) <= 85 and abs(e) <= 85
            and cell != keep)


def _random_cell(rng: random.Random, tm: TileMap, keep: Axial) -> Axial:
    for _ in range(200):
        cell = hex.world_to_axial(rng.uniform(ROUTE_N_MIN, 85.0), rng.uniform(-85.0, 85.0))
        if _cell_ok(tm, cell, keep):
            return cell
    return (2, 2)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _path_len(start: tuple[float, float], pts: Sequence[tuple[float, float]]) -> float:
    total, at = 0.0, start
    for p in pts:
        total += _dist(at, p)
        at = p
    return total


def draw_stops(rng: random.Random, tm: TileMap, keep: Axial, count: int,
               start: tuple[float, float]) -> list[Axial]:
    """`count` cells, pairwise ≥ ROUTE_MIN_GAP_M apart and that far from the
    pilot, inside the playable arena and above the pad rows."""
    stops: list[Axial] = []
    for _ in range(400):
        cell = _random_cell(rng, tm, keep)
        p = hex.axial_to_world(cell)
        if _dist(p, start) < ROUTE_MIN_GAP_M:
            continue
        if any(_dist(p, hex.axial_to_world(s)) < ROUTE_MIN_GAP_M for s in stops):
            continue
        stops.append(cell)
        if len(stops) == count:
            break
    return stops


def route_limit(length_m: float, stops: int) -> float:
    lo, hi = ROUTE_LIMIT
    return float(min(hi, max(lo, math.ceil(length_m / ROUTE_MPS) + ROUTE_SLACK_S * stops)))


def optimal_order(start: tuple[float, float], pts: Sequence[tuple[float, float]]) -> float:
    return min(_path_len(start, [pts[i] for i in perm])
               for perm in itertools.permutations(range(len(pts))))


# ---------------------------------------------------------------- families

def make_route(rng: random.Random, ctx: QuestCtx, qid: int, tier: int, room: bool,
               start: tuple[float, float]) -> Quest | None:
    count = ROUTE_STOPS[tier]
    variant = "" if tier == 1 else rng.choice(("back", "at")) if tier == 2 else "any"
    tag = f"room quest {qid}" if room else f"quest {qid}"
    for _ in range(ROUTE_DRAWS):
        stops = draw_stops(rng, ctx.tm, ctx.keep_cell, count, start)
        if len(stops) < count:
            continue
        pts = [hex.axial_to_world(s) for s in stops]
        order = list(range(count))
        alt: float | None = None
        if variant == "back":
            order.reverse()
        elif variant == "at":
            alt = rng.choice(ROUTE_ALTS)
        if variant == "any":
            best = optimal_order(start, pts)
            if _path_len(start, pts) < ROUTE_ANY_ORDER_RATIO * best:
                continue  # the listed order must not be the answer
            limit, order = route_limit(best, count), []
        else:
            limit = route_limit(_path_len(start, [pts[i] for i in order]), count)
        head = {"": "route", "back": "route back", "at": f"route at {round(alt or 0)} m,",
                "any": "route any order"}[variant]
        # widest: "GAME: room quest 99: route any order 5 stops, 90 s" = 50
        lines = [f"GAME: {tag}: {head} {count} stops, {round(limit)} s"]
        lines += [f"GAME: {tag} stop {i + 1} at {fmt_cell(s)}" for i, s in enumerate(stops)]
        return Quest(qid, "route", variant, tier, room, None, limit, lines,
                     stops=stops, order=order, alt=alt)
    return None


def make_predict(rng: random.Random, ctx: QuestCtx, qid: int, tier: int,
                 start: tuple[float, float]) -> Quest | None:
    """A creep whose march a pilot CAN model: not chewing, going the same way
    on the empty map as on the real one, and going somewhere."""
    seconds = PREDICT_T[tier]
    kinds = PREDICT_KINDS[tier]
    uids = sorted(uid for uid, u in ctx.creeps.items()
                  if u.kind in kinds and not u.chewing)
    rng.shuffle(uids)
    for uid in uids[:12]:  # a dry run is ~150 steps; do not scan a 20-creep wave
        u = ctx.creeps[uid]
        real = predict_position(u, ctx.tm, ctx.flow, seconds, ctx.chew_s)
        flat = predict_position(u, ctx.tm, ctx.flow0, seconds, ctx.chew_s)
        if real is None or flat is None or _dist(real, flat) > 1.0:
            continue
        if _dist(real, (u.n, u.e)) < PREDICT_MIN_MOVE:
            continue
        # widest: "GAME: quest 99: champion at N -97 E -97, in 15 s?" = 49
        lines = [f"GAME: quest {qid}: {u.kind} at {fmt_world(u.n, u.e)}, in {seconds} s?"]
        return Quest(qid, "predict", u.kind, tier, False, None, float(seconds), lines,
                     target=real)
    return None


def make_compute(rng: random.Random, ctx: QuestCtx, qid: int, tier: int, room: bool,
                 drone: DroneView | None, pad: tuple[float, float] | None) -> Quest | None:
    tag = f"room quest {qid}" if room else f"quest {qid}"
    keep = hex.axial_to_world(ctx.keep_cell)
    choices: list[str] = ["dist"]
    if tier >= 2:
        choices.append("hexes")
        if not room and pad is not None:
            choices.append("dist pad")
        if not room and drone is not None and drone.id in ctx.heard_wave:
            choices += ["gates", "creeps"]
    if tier >= 3 and not room and pad is not None:
        choices.append("hexes pad")
    variant = rng.choice(choices)
    lo, hi = ANSWER_RANGE
    for _ in range(40):
        if variant == "gates":
            answer = float(len(ctx.gates) * 10 + ctx.wave)
            lines = [f"GAME: {tag}: alt = gates x 10 + wave"]
        elif variant == "creeps":
            answer = float(ctx.wave_size)
            lines = [f"GAME: {tag}: alt = creeps this wave"]
        else:
            cell = _random_cell(rng, ctx.tm, ctx.keep_cell)
            origin = pad if variant.endswith("pad") and pad is not None else keep
            where = "pad to" if variant.endswith("pad") else "to"
            if variant.startswith("dist"):
                k = rng.choice(COMPUTE_DIVISORS)
                answer = _dist(origin, hex.axial_to_world(cell)) / k
                # widest: "GAME: room quest 99: alt = dist to N -97 E -97 / 6" = 50
                lines = [f"GAME: {tag}: alt = dist {where} {fmt_cell(cell)} / {k}"]
            else:
                origin_cell = hex.world_to_axial(*origin)
                answer = float(hex.distance(origin_cell, cell))
                lines = [f"GAME: {tag}: alt = hexes {where} {fmt_cell(cell)}"]
        if lo <= answer <= hi:
            return Quest(qid, "compute", variant, tier, room, None, COMPUTE_S, lines,
                         answer=answer,
                         hold=DwellTracker(COMPUTE_RADIUS, float("inf"), COMPUTE_HOLD_S))
    return None


# ------------------------------------------------------------------ board

class QuestBoard:
    def __init__(self) -> None:
        self.rng = random.Random(0)
        self.enrolled: set[str] = set()  # student ids who said "quest"
        self.personal: dict[str, Quest] = {}  # drone id -> its quest
        self.next_at: dict[str, float] = {}  # drone id -> seconds to the next issue
        self.seq: dict[str, int] = {}  # student id -> quests issued this round
        self.last_family: dict[str, Family] = {}
        self.still: dict[str, float] = {}  # drone id -> seconds parked
        self.room: Quest | None = None
        self.pending_buff: Buff | None = None
        self._buff_flip = False

    def clear(self, rng: random.Random) -> None:
        """A new round: quests, clocks and ids start over. Enrolment stays —
        a pilot who said `quest` should not have to say it after every
        instructor reset (and the answer bots say it once)."""
        self.rng = rng
        self.personal.clear()
        self.next_at.clear()
        self.seq.clear()
        self.last_family.clear()
        self.still.clear()
        self.room = None
        self.pending_buff = None

    # ----------------------------------------------------------- enrolment

    def enrol(self, drone: DroneView) -> bool:
        """True if newly enrolled (the first quest comes soon)."""
        if drone.student_id in self.enrolled:
            return False
        self.enrolled.add(drone.student_id)
        self.next_at[drone.id] = QUEST_FIRST_S
        return True

    def unenrol(self, drone: DroneView) -> Quest | None:
        self.enrolled.discard(drone.student_id)
        self.next_at.pop(drone.id, None)
        return self.personal.pop(drone.id, None)

    def drop(self, drone_id: str) -> Quest | None:
        """A crash or a lost link ends the quest; the pilot keeps their
        enrolment and gets the next one after the usual gap."""
        q = self.personal.pop(drone_id, None)
        if q is not None:
            self.next_at[drone_id] = QUEST_GAP_S
        return q

    # --------------------------------------------------------------- issue

    def _next_id(self, student_id: str) -> int:
        n = min(QUEST_ID_MAX, self.seq.get(student_id, 0) + 1)
        self.seq[student_id] = n
        return n

    def issue(self, world: WorldAPI, ctx: QuestCtx, drone: DroneView,
              family: Family | None = None, tier: int | None = None) -> Quest | None:
        """A fresh personal quest for `drone`, announced. Family: the caller's,
        else a random one that is not the pilot's last and can be built right
        now (predict needs a modellable creep). None if nothing fits."""
        tier = tier if tier is not None else tier_for(ctx.wave)
        options = [family] if family else [f for f in FAMILIES
                                           if f != self.last_family.get(drone.id)]
        self.rng.shuffle(options)
        start = (drone.n, drone.e)
        pad = _pad_of(world, drone)
        qid = self._next_id(drone.student_id)
        for fam in options:
            if fam == "route":
                q = make_route(self.rng, ctx, qid, tier, False, start)
            elif fam == "predict":
                q = make_predict(self.rng, ctx, qid, tier, start)
            else:
                q = make_compute(self.rng, ctx, qid, tier, False, drone, pad)
            if q is not None:
                q.owner = drone.id
                self.personal[drone.id] = q
                self.last_family[drone.id] = fam
                self.next_at.pop(drone.id, None)
                for line in q.lines:
                    world.send_text(drone.id, line)
                return q
        self.seq[drone.student_id] -= 1  # nothing issued: the number is not spent
        self.next_at[drone.id] = QUEST_GAP_S / 2  # try again soon
        return None

    def issue_room(self, world: WorldAPI, ctx: QuestCtx) -> Quest | None:
        """This wave's room quest, broadcast; id = the wave number."""
        tier = tier_for(ctx.wave)
        fam: Family = self.rng.choice(ROOM_FAMILIES)
        keep = hex.axial_to_world(ctx.keep_cell)
        qid = min(QUEST_ID_MAX, ctx.wave)
        q = (make_route(self.rng, ctx, qid, tier, True, keep) if fam == "route"
             else make_compute(self.rng, ctx, qid, tier, True, None, None))
        if q is None:
            return None
        q.left_s = min(q.left_s, ROOM_QUEST_S) if fam == "route" else ROOM_QUEST_S
        self.room = q
        for line in q.lines:
            world.broadcast_text(line)
        world.emit_event("quest_room", f"{q.lines[0][6:]} — everyone: first to solve it wins",
                         data={"quest": q.qid, "family": q.family, "tier": q.tier})
        return q

    def wave_started(self, world: WorldAPI, ctx: QuestCtx) -> Buff | None:
        """Called from the mission's wave start, after the gate lines: hand
        back the buff that applies to THIS wave, and issue a room quest if
        none is open. An unsolved room quest keeps its own clock — a room
        that clears waves fast is not punished with a cut-off quest; only
        the 60 s expiry is a miss (tick() handles it)."""
        buff, self.pending_buff = self.pending_buff, None
        if self.room is not None and self.room.solved_by is not None:
            self.room = None  # solved: the wall has seen it; make room for the next
        if self.room is None and ctx.wave >= ROOM_QUEST_FROM_WAVE:
            self.issue_room(world, ctx)
        return buff

    def _miss(self, world: WorldAPI, q: Quest) -> None:
        self._buff_flip = not self._buff_flip
        self.pending_buff = Buff("hp" if self._buff_flip else "speed")
        # widest: "GAME: room quest 99 missed, next wave faster" = 44
        world.broadcast_text(f"GAME: {q.tag} missed, next wave {self.pending_buff.text}")
        world.emit_event("quest_missed",
                         f"nobody solved {q.tag} ({q.family}) — next wave comes "
                         f"{self.pending_buff.text}",
                         data={"quest": q.qid, "family": q.family,
                               "buff": self.pending_buff.kind})

    # ---------------------------------------------------------------- tick

    def tick(self, world: WorldAPI, ctx: QuestCtx, drones: Sequence[DroneView],
             dt: float) -> list[Resolved]:
        out: list[Resolved] = []
        by_id = {d.id: d for d in drones}
        for d in drones:  # stillness, for predict: parked, not chasing
            slow = math.hypot(d.vn, d.ve) < PREDICT_STILL_V and d.armed and not d.crashed
            self.still[d.id] = self.still.get(d.id, 0.0) + dt if slow else 0.0
        for drone_id in list(self.still):
            if drone_id not in by_id:
                del self.still[drone_id]

        for drone_id, q in list(self.personal.items()):
            owner = by_id.get(drone_id)
            if owner is None:
                continue  # gone: the mission's drop() handles the event
            q.left_s -= dt
            if abs(q.left_s) < _EPS:
                q.left_s = 0.0
            verdict = self._check(world, ctx, q, [owner], dt)
            if verdict is not None:
                del self.personal[drone_id]
                self.next_at[drone_id] = QUEST_GAP_S
                out.append(verdict)

        if self.room is not None and self.room.solved_by is None:
            self.room.left_s -= dt
            verdict = self._check(world, ctx, self.room, drones, dt)
            if verdict is not None:
                if verdict.kind == "solved":
                    self.room.solved_by = verdict.drone.id if verdict.drone else "?"
                else:
                    self._miss(world, self.room)
                    self.room = None
                out.append(verdict)

        if ctx.state == "active" and ctx.wave >= QUEST_FROM_WAVE:
            issued = 0
            for d in drones:
                if issued >= ISSUE_PER_TICK:
                    break
                if (d.student_id not in self.enrolled or d.id in self.personal
                        or not d.connected or not d.armed or d.crashed):
                    continue
                left = self.next_at.get(d.id, QUEST_GAP_S) - dt
                self.next_at[d.id] = left
                if left <= _EPS and self.issue(world, ctx, d) is not None:
                    issued += 1
        return out

    def _check(self, world: WorldAPI, ctx: QuestCtx, q: Quest, drones: Sequence[DroneView],
               dt: float) -> Resolved | None:
        if q.family == "route":
            for d in drones:
                if self._route_step(world, q, d):
                    return Resolved(q, "solved", d)
        elif q.family == "predict":
            if q.left_s <= 0:
                assert q.target is not None
                for d in drones:
                    if (d.armed and not d.crashed
                            and _dist((d.n, d.e), q.target) <= PREDICT_RADIUS
                            and self.still.get(d.id, 0.0) >= PREDICT_STILL_S):
                        return Resolved(q, "solved", d)
                return self._expire(world, q)
        else:
            assert q.hold is not None
            assert q.answer is not None
            keep_n, keep_e = hex.axial_to_world(ctx.keep_cell)
            answer = q.answer
            hit = q.hold.update(drones, keep_n, keep_e, dt,
                                eligible=lambda v: abs(v.alt - answer) < COMPUTE_TOL)
            if hit is not None:
                return Resolved(q, "solved", hit)
        if q.left_s <= 0:
            return self._expire(world, q)
        return None

    def _expire(self, world: WorldAPI, q: Quest) -> Resolved:
        if not q.room:
            assert q.owner is not None
            world.send_text(q.owner, f"GAME: {q.tag} expired")
        return Resolved(q, "expired")

    def _route_step(self, world: WorldAPI, q: Quest, d: DroneView) -> bool:
        """Advance this drone's progress on a route; True when it finished."""
        if not d.armed or d.crashed:
            return False
        done = q.progress.setdefault(d.id, [])
        remaining = [i for i in (q.order or range(len(q.stops))) if i not in done]
        if not remaining:
            return False
        wanted = remaining if not q.order else remaining[:1]
        for i in wanted:
            n, e = hex.axial_to_world(q.stops[i])
            if _dist((d.n, d.e), (n, e)) > ROUTE_TOUCH_M:
                continue
            if q.alt is not None and abs(d.alt - q.alt) > ROUTE_ALT_TOL:
                continue
            done.append(i)
            left = len(q.stops) - len(done)
            if left == 0:
                return True
            # widest: "GAME: room quest 99 stop 5 ok, 4 to go" = 38
            world.send_text(d.id, f"GAME: {q.tag} stop {i + 1} ok, {left} to go")
            return False
        return False

    # ----------------------------------------------------------------- hud

    def hud(self, solved: int, missed: int) -> dict:
        room = None
        if self.room is not None:
            room = {"id": self.room.qid, "family": self.room.family,
                    "left_s": max(0, math.ceil(self.room.left_s)),
                    "solved": self.room.solved_by is not None}
        return {"solved": solved, "missed": missed, "room": room}


def _pad_of(world: WorldAPI, drone: DroneView) -> tuple[float, float] | None:
    pads = world.config.pads
    slot = drone.sysid - 1
    if 0 <= slot < len(pads):
        return hex.axial_to_world(pads[slot])
    return None


def room_marks(q: Quest | None) -> Iterable[tuple[str, Axial, dict]]:
    """Projector markers for a room route's stops: (id, cell, data)."""
    if q is None or not q.room or q.family != "route":
        return ()
    touched: set[int] = set()
    for done in q.progress.values():
        touched.update(done)
    return ((f"quest_mark_{q.qid}_{i + 1}", cell,
             {"label": str(i + 1), "quest": q.qid, "done": i in touched})
            for i, cell in enumerate(q.stops))
