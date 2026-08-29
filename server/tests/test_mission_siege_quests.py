"""Quests through the WorldAPI seam: enrolment, each family solved by a
scripted drone, expiry, the room quest and its miss penalty, cadence."""

import math
import random

from app.game import hex
from app.game.missions.siege import KINDS, QUEST_POINTS, SiegeMission
from app.game.quests import (
    COMPUTE_HOLD_S,
    COMPUTE_S,
    ISSUE_PER_TICK,
    PREDICT_T,
    QUEST_FIRST_S,
    QUEST_GAP_S,
    QUEST_POOL_EACH,
    ROOM_QUEST_POOL_EACH,
    ROOM_QUEST_S,
    ROUTE_ALT_TOL,
)
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, freeze_waves, texts


def make(seats=("d0",), wave=2, active=False):
    """A siege past the first wave. `active`: one creep that never moves
    holds the wave open (else the wave machine would clear it at once)."""
    world = FakeWorld()
    world.views = [view(d, n=-90.0, e=-76.0 + 6 * i, alt=6.0) for i, d in enumerate(seats)]
    m = SiegeMission()
    world.start(m)
    freeze_waves(m)
    m.wave = wave
    if active:
        hold_creep(m)
        m.state = "active"
    return world, m


def say(world, m, text, drone_id="d0"):
    world.text(m, next(v for v in world.views if v.id == drone_id), text)
    return world.texts[-1][1]


def drone(world, drone_id="d0"):
    return next(v for v in world.views if v.id == drone_id)


def park(world, drone_id, n, e, alt):
    world.views = [view(drone_id, n=n, e=e, alt=alt) if v.id == drone_id else v
                   for v in world.views]


def hold_creep(m):
    """A creep that never moves, so the wave never clears and the state stays active."""
    return add_creep(m, (12, -6), uid=999, speed=0.0)


# --------------------------------------------------------------- enrolment

def test_quests_are_opt_in():
    world, m = make(active=True)
    world.run(m, QUEST_FIRST_S + QUEST_GAP_S)
    assert not any("quest" in t for t in texts(world)), "nobody asked"
    assert say(world, m, "quest") == "GAME: quests on, first one soon"
    assert say(world, m, "quest") == "GAME: quests already on"
    world.run(m, QUEST_FIRST_S + 0.2)
    assert "d0" in m.quests.personal
    head = next(t for t in texts(world) if t.startswith("GAME: quest 1:"))
    assert head.split(": ")[2].split()[0] in ("route", "runner", "grunt", "alt")
    assert say(world, m, "quest off") == "GAME: quests off"
    assert "d0" not in m.quests.personal and m.quests.enrolled == set()
    assert_grammar(world)


def test_no_quests_before_wave_two_or_while_building():
    world, m = make(wave=1, active=True)
    say(world, m, "quest")
    world.run(m, QUEST_FIRST_S + 5)
    assert not m.quests.personal
    m.wave, m.state = 3, "build"
    world.run(m, QUEST_FIRST_S + 5)
    assert not m.quests.personal
    m.state = "active"  # the clock to the first quest runs on active time
    world.run(m, QUEST_FIRST_S + 0.2)
    assert "d0" in m.quests.personal


# ------------------------------------------------------------------ route

def test_a_route_is_flown_in_order_and_pays():
    world, m = make(seats=("d0", "d1"))
    q = m.quests.issue(world, m, drone(world), family="route", tier=1)
    assert q is not None and len(q.stops) == 3
    assert texts(world)[-4].startswith("GAME: quest 1: route 3 stops,")
    assert texts(world)[-3:] == [
        f"GAME: quest 1 stop {i + 1} at N {round(hex.axial_to_world(s)[0])} "
        f"E {round(hex.axial_to_world(s)[1])}" for i, s in enumerate(q.stops)]
    before, pool = world.score, m.pool
    # the third stop first: ignored, the route is ordered
    park(world, "d0", *hex.axial_to_world(q.stops[2]), 10.0)
    world.run(m, 0.3)
    assert q.progress.get("d0", []) == []
    for i, stop in enumerate(q.stops):
        park(world, "d0", *hex.axial_to_world(stop), 10.0)
        world.run(m, 0.2)
        if i < 2:
            assert texts(world)[-1] == f"GAME: quest 1 stop {i + 1} ok, {2 - i} to go"
    assert texts(world)[-1] == (f"GAME: quest 1 solved! +{QUEST_POINTS}, "
                                f"pool +{2 * QUEST_POOL_EACH}")
    assert world.score == before + QUEST_POINTS
    assert world.scores[-1] == (QUEST_POINTS, "D0 solved quest 1 (route)", "s-d0")
    assert m.pool == pool + 2 * QUEST_POOL_EACH and m.stats.quests_solved == 1
    assert world.events[-1]["kind"] == "score", "a named feed row"
    assert "d0" not in m.quests.personal
    assert_grammar(world)


def test_a_route_at_altitude_needs_the_altitude():
    world, m = make()
    q = m.quests.issue(world, m, drone(world), family="route", tier=1)
    q.alt = 18.0
    n, e = hex.axial_to_world(q.stops[0])
    park(world, "d0", n, e, 18.0 + ROUTE_ALT_TOL + 1)
    world.run(m, 0.3)
    assert q.progress.get("d0", []) == []
    park(world, "d0", n, e, 18.5)
    world.run(m, 0.2)
    assert q.progress["d0"] == [0]


def test_a_route_expires_and_the_next_comes_after_the_gap():
    world, m = make(active=True)
    say(world, m, "quest")
    q = m.quests.issue(world, m, drone(world), family="route", tier=1)
    world.run(m, q.left_s + 0.2)
    assert texts(world)[-1] == "GAME: quest 1 expired"
    assert "d0" not in m.quests.personal
    world.run(m, QUEST_GAP_S - 1.0)
    assert "d0" not in m.quests.personal, "the gap"
    world.run(m, 1.3)
    assert m.quests.personal["d0"].qid == 2


# ---------------------------------------------------------------- predict

def test_predict_is_solved_by_parking_where_the_creep_will_be():
    world, m = make()
    add_creep(m, (0, 10), speed=2.0)
    q = m.quests.issue(world, m, drone(world), family="predict", tier=1)
    assert q is not None and q.target is not None
    head = texts(world)[-1]
    assert head.startswith("GAME: quest 1: grunt at N ") and head.endswith(", in 8 s?")
    park(world, "d0", q.target[0], q.target[1], 6.0)
    world.run(m, PREDICT_T[1] + 0.3)
    assert texts(world)[-1] == f"GAME: quest 1 solved! +{QUEST_POINTS}, pool +{QUEST_POOL_EACH}"
    assert m.stats.quests_solved == 1


def test_predict_fails_a_drone_still_chasing():
    world, m = make()
    add_creep(m, (0, 10), speed=2.0)
    q = m.quests.issue(world, m, drone(world), family="predict", tier=1)
    world.views = [view("d0", n=q.target[0], e=q.target[1], alt=6.0, vn=2.0)]
    world.run(m, PREDICT_T[1] + 0.3)
    assert texts(world)[-1] == "GAME: quest 1 expired"


def test_predict_survives_the_creep_dying():
    world, m = make()
    add_creep(m, (0, 10), speed=2.0)
    q = m.quests.issue(world, m, drone(world), family="predict", tier=1)
    world.run(m, 2.0)
    m.creeps.clear()  # a tower got it
    park(world, "d0", q.target[0], q.target[1], 6.0)
    world.run(m, PREDICT_T[1])
    assert "solved" in texts(world)[-1]


# ---------------------------------------------------------------- compute

def test_compute_is_solved_by_hovering_the_keep_at_the_answer():
    world, m = make()
    q = m.quests.issue(world, m, drone(world), family="compute", tier=1)
    assert q is not None and q.variant == "dist" and q.answer is not None
    park(world, "d0", 0.0, 0.0, q.answer + 1.6)
    world.run(m, COMPUTE_HOLD_S + 0.5)
    assert "solved" not in texts(world)[-1], "±1 m"
    park(world, "d0", 0.0, 0.0, q.answer - 0.5)
    world.run(m, COMPUTE_HOLD_S + 0.3)
    assert texts(world)[-1].startswith("GAME: quest 1 solved!")


def test_compute_expires_quietly_wrong():
    world, m = make()
    q = m.quests.issue(world, m, drone(world), family="compute", tier=1)
    park(world, "d0", 0.0, 0.0, q.answer + 5)
    world.run(m, COMPUTE_S + 0.3)
    assert texts(world)[-1] == "GAME: quest 1 expired"
    assert not any("higher" in t or "lower" in t for t in texts(world)), "no hi/lo hints"


# ------------------------------------------------------------- room quest

def test_no_room_quest_until_somebody_opts_in():
    world, m = make(seats=("d0", "d1"))
    m._start_wave(world, 3)
    assert m.quests.room is None and not any("room quest" in t for t in texts(world))
    m.quests.enrol(drone(world))
    m.creeps.clear(), m.roster.clear()
    m.pending = 0
    m._start_wave(world, 4)
    assert m.quests.room is not None and m.quests.room.qid == 4


def test_a_room_quest_opens_with_the_wave_and_a_miss_buffs_the_next():
    world, m = make(seats=("d0", "d1"))
    m.quests.enrol(drone(world))
    m.quests.rng = random.Random(5)
    m._start_wave(world, 3)
    room = m.quests.room
    assert room is not None and room.qid == 3 and room.family in ("route", "compute")
    head = next(t for t in texts(world) if t.startswith("GAME: room quest 3:"))
    assert head and any(ev["kind"] == "quest_room" for ev in world.events)
    if room.family == "route":
        marks = [e for e in m.entities(world) if e.kind == "quest_mark"]
        assert [e.id for e in marks] == [f"quest_mark_3_{i}" for i in range(1, len(room.stops) + 1)]
        assert marks[0].data == {"label": "1", "quest": 3, "done": False}
    assert m.hud()["quests"]["room"] == {"id": 3, "family": room.family,
                                         "left_s": math.ceil(room.left_s), "solved": False}
    m.creeps.clear(), m.roster.clear()
    m.pending = 0
    m._start_wave(world, 4)  # a fast clear: the open quest keeps its clock
    assert m.quests.room is room and not any("missed" in t for t in texts(world))
    hold_creep(m)
    world.run(m, ROOM_QUEST_S + 0.3)  # …and nobody solved it
    assert "GAME: room quest 3 missed, next wave +1 hp" in texts(world)
    assert m.quests.room is None and m.stats.quests_missed == 1
    m.creeps.clear(), m.roster.clear()
    m.pending = 0
    m._start_wave(world, 5)
    assert "GAME: wave 5 buffed: +1 hp" in texts(world)
    assert m.buff is not None
    m._spawn_creep()
    spawned = m.creeps[m._uid]
    assert spawned.hp == KINDS[spawned.kind].hp + 1 and spawned.max_hp == spawned.hp
    assert any(ev["kind"] == "quest_missed" for ev in world.events)
    assert_grammar(world)


def test_room_quest_expiry_mid_wave_alternates_the_buff():
    world, m = make()
    m.quests.enrol(drone(world))
    hold_creep(m)
    m._start_wave(world, 3)
    hold_creep(m)
    world.run(m, ROOM_QUEST_S + 0.3)
    assert "GAME: room quest 3 missed, next wave +1 hp" in texts(world)
    assert m.quests.room is None and m.stats.quests_missed == 1
    m._start_wave(world, 4)
    assert "GAME: wave 4 buffed: +1 hp" in texts(world)
    hold_creep(m)
    world.run(m, ROOM_QUEST_S + 0.3)
    assert "GAME: room quest 4 missed, next wave faster" in texts(world)
    m._start_wave(world, 5)
    m._spawn_creep()
    spawned = m.creeps[m._uid]
    base = min(2.5, 1.5 + 0.1 * 4) * KINDS[spawned.kind].speed_mult
    assert abs(spawned.speed - base * 1.2) < 1e-9
    # the wave clear ends the penalty
    m.creeps.clear(), m.roster.clear()
    m.pending = 0
    world.run(m, 0.3)
    assert m.state == "build" and m.buff is None


def test_the_first_pilot_to_solve_a_room_quest_pays_the_pool():
    world, m = make(seats=("d0", "d1", "d2"))
    m.quests.enrol(drone(world, "d2"))
    m.quests.rng = random.Random(1)
    m._start_wave(world, 3)
    while m.quests.room is None or m.quests.room.family != "compute":
        m.quests.room = None
        m.quests.issue_room(world, m)
    room = m.quests.room
    hold_creep(m)
    park(world, "d1", 0.0, 0.0, room.answer)
    world.run(m, COMPUTE_HOLD_S + 0.3)
    assert room.solved_by == "d1"
    assert ("d1", f"GAME: room quest 3 solved! +{QUEST_POINTS}, pool +{3 * ROOM_QUEST_POOL_EACH}") \
        in world.texts
    assert ("d0", "GAME: room quest 3 solved!") in world.texts
    assert ("d2", "GAME: room quest 3 solved!") in world.texts
    ev = next(ev for ev in world.events if ev["kind"] == "quest_solved")
    assert ev["msg"].startswith("D1 solved room quest 3 (compute)! pool +")
    assert m.pool == 3 * ROOM_QUEST_POOL_EACH and m.stats.quests_solved == 1
    assert m.hud()["quests"]["room"]["solved"] is True
    park(world, "d2", 0.0, 0.0, room.answer)
    world.run(m, COMPUTE_HOLD_S + 0.3)
    assert m.stats.quests_solved == 1, "first only"
    m._start_wave(world, 4)
    assert not any("missed" in t for t in texts(world))


# --------------------------------------------------------- cadence, drops

def test_sixty_enrolled_pilots_get_quests_in_batches():
    seats = tuple(f"d{i}" for i in range(60))
    world, m = make(seats=seats, active=True)
    for d in list(world.views):
        m.quests.enrol(d)
    world.run(m, QUEST_FIRST_S - 0.05)
    assert not m.quests.personal
    world.run(m, 0.15)
    assert 0 < len(m.quests.personal) <= 2 * ISSUE_PER_TICK
    world.run(m, 60 / ISSUE_PER_TICK * 0.1 + 0.3)
    assert len(m.quests.personal) == 60
    assert all(q.qid == 1 for q in m.quests.personal.values())


def test_a_crash_drops_the_quest_and_says_so():
    world, m = make()
    m.quests.enrol(drone(world))
    m.quests.issue(world, m, drone(world), family="route", tier=1)
    world.drone_event(m, drone(world), "crashed")
    assert texts(world)[-1] == "GAME: quest 1 off: crashed"
    assert "d0" not in m.quests.personal and "s-d0" in m.quests.enrolled
    m.quests.issue(world, m, drone(world), family="route", tier=1)
    world.drone_event(m, drone(world), "disconnected")
    assert "d0" not in m.quests.personal and "off" not in texts(world)[-1]


def test_reset_clears_the_board_and_renumbers():
    world, m = make()
    m.quests.enrol(drone(world))
    m.quests.issue(world, m, drone(world), family="route", tier=1)
    m.stats.quests_solved = 3
    m.reset(world)
    assert m.quests.personal == {} and m.quests.room is None
    assert m.quests.enrolled == {"s-d0"}, "enrolment survives an instructor reset"
    assert m.hud()["quests"] == {"solved": 0, "missed": 0, "room": None}
    m.state, m.wave = "active", 2
    q = m.quests.issue(world, m, drone(world), family="route", tier=1)
    assert q is not None and q.qid == 1


def test_a_late_joiner_is_not_asked_to_count_a_wave_it_did_not_hear():
    world, m = make(seats=("d0",), active=True)
    m._start_wave(world, 3)
    late = view("d1", n=-90.0, e=-70.0, alt=6.0)
    world.views.append(late)
    world.drone_event(m, late, "connected")
    assert "d1" not in m.heard_wave and "d0" in m.heard_wave


def test_quest_dice_do_not_move_the_gate_dice():
    """Gate sequences per seed are pinned by the older siege tests; the quest
    RNG is a second stream drawn after siege's own, and its own."""
    _world, m = make()
    _world2, m2 = make()
    assert [m.rng.random() for _ in range(3)] == [m2.rng.random() for _ in range(3)]
    assert m.quests.rng.random() == m2.quests.rng.random() != m.rng.random()
