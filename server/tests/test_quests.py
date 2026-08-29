"""The quest module on its own: generators, the dry-run predictor, and every
line at its widest through the STATUSTEXT law."""

import dataclasses
import random

from app.game import hex, path
from app.game.quests import (
    ANSWER_RANGE,
    COMPUTE_DIVISORS,
    ROUTE_ANY_ORDER_RATIO,
    ROUTE_LIMIT,
    ROUTE_MIN_GAP_M,
    ROUTE_STOPS,
    _path_len,
    draw_stops,
    make_compute,
    make_predict,
    make_route,
    optimal_order,
    predict_position,
    route_limit,
    tier_for,
)
from app.game.tiles import TileMap
from app.game.units import GroundUnit, step_units
from tests.support.harness import check_text, view

KEEP = (0, 0)


class Ctx:
    """The QuestCtx a generator reads, hand-built."""

    def __init__(self, wave=3, creeps=None, gates=2, wave_size=12):
        self.wave = wave
        self.state = "active"
        self.tm = TileMap()
        self.flow = path.flood(self.tm, KEEP, climb=1)
        self.flow0 = self.flow
        self.creeps = creeps or {}
        self.beacons = {}
        self.gates = ((86.0, 3.0), (0.0, 83.0))[:gates]
        self.wave_size = wave_size
        self.heard_wave = {"d0"}
        self.chew_s = 6.0
        self.keep_cell = KEEP


def creep(cell, speed=2.0, kind="grunt", uid=1):
    n, e = hex.axial_to_world(cell)
    return GroundUnit(uid=uid, n=n, e=e, speed=speed, kind=kind)


def test_tiers_follow_the_gate_bands():
    assert [tier_for(w) for w in (1, 4, 5, 7, 8, 20)] == [1, 1, 2, 2, 3, 3]


def test_predict_is_a_dry_run_of_the_real_walker():
    ctx = Ctx()
    u = creep((0, 10))
    twin = dataclasses.replace(u)
    where = predict_position(u, ctx.tm, ctx.flow, 8.0, ctx.chew_s)
    for _ in range(80):
        step_units([twin], ctx.tm, ctx.flow, 0.1, ctx.chew_s)
    assert where == (twin.n, twin.e)
    assert (u.n, u.e) == (creep((0, 10)).n, creep((0, 10)).e), "the original never moved"
    assert predict_position(creep((0, 1), speed=5.0), ctx.tm, ctx.flow, 8.0, 6.0) is None, \
        "a creep that reaches the Keep first has no answer"


def test_stops_keep_their_distance_and_stay_playable():
    rng = random.Random(3)
    tm = TileMap()
    for _ in range(20):
        stops = draw_stops(rng, tm, KEEP, 5, start=(-90.0, -76.0))
        assert len(stops) == 5
        pts = [hex.axial_to_world(s) for s in stops]
        for i, a in enumerate(pts):
            assert a[0] >= -70 and abs(a[0]) <= 85 and abs(a[1]) <= 85
            assert ((a[0] + 90) ** 2 + (a[1] + 76) ** 2) ** 0.5 >= ROUTE_MIN_GAP_M
            for b in pts[i + 1:]:
                assert ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 >= ROUTE_MIN_GAP_M


def test_route_limit_is_clamped():
    lo, hi = ROUTE_LIMIT
    assert route_limit(0.0, 3) == lo
    assert route_limit(10_000.0, 5) == hi
    assert lo < route_limit(150.0, 3) < hi


def test_any_order_routes_make_the_listed_order_a_bad_answer():
    ctx = Ctx(wave=9)
    seen = 0
    for seed in range(12):
        q = make_route(random.Random(seed), ctx, 5, tier=3, room=False, start=(0.0, 0.0))
        assert q is not None and q.variant == "any" and q.order == []
        pts = [hex.axial_to_world(s) for s in q.stops]
        assert _path_len((0.0, 0.0), pts) >= ROUTE_ANY_ORDER_RATIO * optimal_order((0.0, 0.0), pts)
        seen += 1
    assert seen == 12 and len(q.stops) == ROUTE_STOPS[3]


def test_generators_are_deterministic_per_seed():
    ctx = Ctx(creeps={1: creep((0, 10))})
    a = make_route(random.Random(7), ctx, 1, 2, False, (0.0, 0.0))
    b = make_route(random.Random(7), ctx, 1, 2, False, (0.0, 0.0))
    assert a is not None and a.lines == b.lines
    c = make_compute(random.Random(7), ctx, 1, 2, False, view(), (-90.0, -76.0))
    d = make_compute(random.Random(7), ctx, 1, 2, False, view(), (-90.0, -76.0))
    assert c is not None and c.lines == d.lines and c.answer == d.answer


def test_every_line_fits_at_the_widest():
    """Two-digit ids, the far corner cell, the longest kind and variant."""
    ctx = Ctx(wave=9, gates=2)
    for seed in range(30):
        q = make_route(random.Random(seed), ctx, 99, 3, True, (0.0, 0.0))
        assert q is not None
        for line in q.lines:
            check_text(line)
    check_text("GAME: room quest 99 stop 5 at N -97 E -97")  # the widest a cell prints
    for variant_room in (True, False):
        for seed in range(40):
            q = make_compute(random.Random(seed), ctx, 99, 3, variant_room,
                             None if variant_room else view(), None if variant_room
                             else (-90.0, -76.0))
            assert q is not None
            for line in q.lines:
                check_text(line)
    # predict: the longest kind the family issues, at the far corner
    ctx = Ctx(wave=9, creeps={1: creep(hex.world_to_axial(-90.0, -90.0), kind="runner", speed=3.0)})
    q = make_predict(random.Random(1), ctx, 99, 3, (0.0, 0.0))
    u = ctx.creeps[1]
    assert q is not None
    assert q.lines == [f"GAME: quest 99: runner at N {round(u.n)} E {round(u.e)}, in 15 s?"]
    check_text("GAME: quest 99: runner at N -97 E -97, in 15 s?")
    for text in ("GAME: room quest 99 stop 5 ok, 4 to go", "GAME: quest 99 solved! +5, pool +192",
                 "GAME: room quest 99 solved! +5, pool +192", "GAME: quest 99 expired",
                 "GAME: quest 99 off: crashed", "GAME: room quest 99 missed, next wave faster",
                 "GAME: wave 100 buffed: faster", "GAME: quests on, first one soon"):
        check_text(text)


def test_predict_only_picks_a_creep_a_pilot_can_model():
    tm = TileMap()
    ctx = Ctx(creeps={1: creep((0, 10), speed=0.5)})  # 4 m in 8 s: too little
    assert make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0)) is None
    ctx = Ctx(creeps={1: creep((0, 10), speed=2.0, kind="brute")})  # not a tier-1 kind
    assert make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0)) is None
    ctx = Ctx(creeps={1: creep((0, 10), speed=2.0)})
    ctx.creeps[1].chew_cell = (0, 9)  # chewing: nobody can model that
    assert make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0)) is None
    # a wall on its path: the real field and the empty one disagree
    ctx = Ctx(creeps={1: creep((0, 10), speed=2.0)})
    for cell in [*hex.ring((0, 6), 1), (0, 6)]:
        tm.place(cell, "steel"), tm.place(cell, "steel")
    ctx.tm, ctx.flow = tm, path.flood(tm, KEEP, climb=1)
    assert make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0)) is None
    ctx = Ctx(creeps={1: creep((0, 10), speed=2.0)})
    q = make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0))
    assert q is not None and q.target is not None and q.left_s == 8


def test_compute_answers_are_what_the_text_says():
    ctx = Ctx(wave=9, gates=2, wave_size=17)
    pad = (-90.0, -76.0)
    seen = set()
    for seed in range(200):
        q = make_compute(random.Random(seed), ctx, 1, 3, False, view(), pad)
        assert q is not None and ANSWER_RANGE[0] <= q.answer <= ANSWER_RANGE[1]
        seen.add(q.variant)
        line = q.lines[0]
        if q.variant == "gates":
            assert q.answer == 2 * 10 + 9
        elif q.variant == "creeps":
            assert q.answer == 17
        else:
            n, e = [int(x) for x in line.split(" N ")[1].replace(" E ", " ").split()[:2]]
            cell = hex.world_to_axial(n, e)
            origin = pad if "pad" in q.variant else (0.0, 0.0)
            if q.variant.startswith("dist"):
                k = int(line.rsplit("/", 1)[1])
                assert k in COMPUTE_DIVISORS
                cn, ce = hex.axial_to_world(cell)
                dist = ((cn - origin[0]) ** 2 + (ce - origin[1]) ** 2) ** 0.5
                assert abs(q.answer - dist / k) < 1e-6
            else:
                assert q.answer == hex.distance(hex.world_to_axial(*origin), cell)
    assert seen == {"dist", "dist pad", "hexes", "hexes pad", "gates", "creeps"}


def test_predict_waits_while_a_beacon_stands_and_room_routes_fit_their_clock():
    ctx = Ctx(creeps={1: creep((0, 10), speed=2.0)})
    ctx.beacons = {(6, 0): object()}
    assert make_predict(random.Random(1), ctx, 1, 1, (0.0, 0.0)) is None
    ctx = Ctx(wave=9)
    for seed in range(20):
        q = make_route(random.Random(seed), ctx, 9, 3, True, (0.0, 0.0))
        assert q is not None and q.left_s <= 60 and f", {round(q.left_s)} s" in q.lines[0]
