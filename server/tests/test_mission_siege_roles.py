"""The roles siege announces: repair (ghosts + callouts + points) and scout
(a gate's spotter hears what comes through), and the per-pilot tally."""

from app.game import hex
from app.game.building import PICKUP_DWELL, PLACE_DWELL
from app.game.missions.siege import (
    GATE_LABELS,
    GATES,
    QUARRY,
    REPAIR_CALL_RADIUS,
    REPAIR_POINTS,
    REPAIR_TTL_S,
    SPAWN_GAP,
    SPOT_DWELL,
    SPOT_FEED_EVERY,
    TARGET_EVERY,
    ZAP_DWELL,
    PilotStats,
    SiegeMission,
)
from app.game.units import GroundUnit
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, freeze_waves, hover, texts


def make():
    world = FakeWorld()
    m = SiegeMission()
    world.start(m)
    freeze_waves(m)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    return world, m


def chew(world, m, cell, material="steel", height=2):
    """A wall that a creep bites one tile off."""
    for _ in range(height):
        m.tm.place(cell, material)
    n, e = hex.axial_to_world(cell)
    m.tm.remove_top(cell)  # what the walker's chew does…
    m.repairs.pop(cell, None)
    from app.game.missions.siege import Repair
    m.repairs[cell] = Repair(material, height, world.now)  # …and what siege records
    return n, e


# ----------------------------------------------------------------- repair

def test_a_chewed_cell_becomes_a_ghost_and_a_callout_to_nearby_carriers():
    world, m = make()
    for wall in hex.ring((0, 0), 2):
        m.tm.place(wall, "steel")
        m.tm.place(wall, "steel")
    add_creep(m, (0, 4), speed=1.5)
    world.run(m, 16.0)
    assert m.repairs, "the bite was recorded"
    cell, rep = next(iter(m.repairs.items()))
    assert rep.material == "steel" and rep.need == 2
    ghost = next(e for e in m.entities(world) if e.id == f"repair_{cell[0]}_{cell[1]}")
    assert ghost.kind == "ghost_tile"
    assert ghost.data == {"material": "steel", "need": 2, "have": m.tm.height(cell),
                          "size": hex.HEX_SIZE}
    n, e = hex.axial_to_world(cell)
    # a carrier nearby hears where and how high; an empty-handed drone does not
    m.carry.give("d0", "steel")
    world.views = [view("d0", n=n + 10.0, e=e, alt=8.0), view("d1", n=n + 10.0, e=e + 3, alt=8.0)]
    world.texts.clear()
    world.run(m, TARGET_EVERY + 0.2)
    mine = [t for target, t in world.texts if target == "d0" and t.startswith("GAME: repair at")]
    assert mine and mine[0].endswith(f"hover {2 * m.tm.height(cell) + 4}")
    assert not [t for target, t in world.texts if target == "d1" and "repair at" in t]
    # a clay carrier does not get a steel repair, nor a carrier far away
    m.carry.clear()
    m.carry.give("d0", "clay")
    world.views = [view("d0", n=n + 10.0, e=e, alt=8.0)]
    world.texts.clear()
    world.run(m, TARGET_EVERY + 0.2)
    assert not any("repair at" in t for t in texts(world))
    m.carry.clear()
    m.carry.give("d0", "steel")
    world.views = [view("d0", n=n + REPAIR_CALL_RADIUS + 5, e=e, alt=8.0)]
    world.run(m, TARGET_EVERY + 0.2)
    assert not any("repair at" in t for t in texts(world))
    assert_grammar(world)


def test_a_tile_back_on_the_hole_repairs_scores_and_clears_the_ghost():
    world, m = make()
    cell = (3, 1)
    chew(world, m, cell)
    before = world.score
    m.carry.give("d0", "steel")
    world.views = [hover(cell, alt=2.0 * (m.tm.height(cell) + 1) + 1.0)]
    world.run(m, PLACE_DWELL + 0.2)
    assert m.tm.height(cell) == 2 and cell not in m.repairs
    assert world.score == before + REPAIR_POINTS
    assert any(t.startswith("GAME: repaired! N") and t.endswith("whole again +1")
               for t in texts(world))
    ev = next(ev for ev in world.events if ev["kind"] == "repaired")
    assert ev["student_id"] == "s-d0" and ev["data"] == {"points": REPAIR_POINTS}
    assert m.stats.pilots["s-d0"].repaired == 1
    assert not any(e.id.startswith("repair_") for e in m.entities(world))
    assert_grammar(world)


def test_an_old_repair_ages_out():
    world, m = make()
    chew(world, m, (3, 1))
    m.carry.give("d0", "steel")
    n, e = hex.axial_to_world((3, 1))
    world.views = [view("d0", n=n + 5, e=e, alt=8.0)]
    world.run(m, REPAIR_TTL_S + TARGET_EVERY + 1)
    assert (3, 1) not in m.repairs
    assert any("repair at" in t for t in texts(world)), "it was called while fresh"


# ------------------------------------------------------------------ scout

def test_hovering_a_gate_makes_a_spotter_who_hears_the_spawns():
    world, m = make()
    m._start_wave(world, 1)
    gi = GATES.index(m.gate)
    gn, ge = m.gate
    world.views = [view("d0", n=gn + 3, e=ge, alt=12.0)]
    world.run(m, SPOT_DWELL + 0.2)
    assert m.spotters == {gi: "d0"}
    assert ("d0", f"GAME: you spot gate {GATE_LABELS[gi]}") in world.texts
    assert any(ev["kind"] == "spotter" for ev in world.events)
    world.run(m, SPAWN_GAP + 0.2)  # a creep comes through
    reports = [t for target, t in world.texts if target == "d0" and t.startswith("GAME: gate ")]
    assert reports and reports[-1].startswith(f"GAME: gate {GATE_LABELS[gi]}: ")
    assert "grunt" in reports[-1]
    relayed = [ev for ev in world.events if ev["kind"] == "spotted"]
    assert len(relayed) == 1 and relayed[0]["msg"].startswith("D0 spots gate")
    assert m.stats.pilots["s-d0"].spots == 1
    world.run(m, SPAWN_GAP)  # the next spawn: the spotter hears, the room is throttled
    assert len([ev for ev in world.events if ev["kind"] == "spotted"]) == 1
    # no "drop under" nag for a spotter parked high over a creep
    assert not any("drop under" in t for t in texts(world))
    # leaving the circle hands the post back
    world.views = [view("d0", n=gn + 30, e=ge, alt=12.0)]
    world.run(m, 0.2)
    assert m.spotters == {}
    assert ("d0", f"GAME: gate {GATE_LABELS[gi]} unwatched") in world.texts
    assert_grammar(world)


def test_the_room_hears_a_spotter_again_after_the_throttle():
    world, m = make()
    m._start_wave(world, 1)
    gi = GATES.index(m.gate)
    gn, ge = m.gate
    m.spotters[gi] = "d0"
    world.views = [view("d0", n=gn, e=ge, alt=12.0)]
    m.pending = 20
    world.run(m, SPOT_FEED_EVERY + SPAWN_GAP * 2)
    relayed = [ev for ev in world.events if ev["kind"] == "spotted"]
    assert len(relayed) == 2


def test_the_spot_report_never_overflows():
    world, m = make()
    m.spotters[0] = "d0"
    m._spawned_at = 0
    uid = 1
    for kind, count in (("grunt", 5), ("runner", 6), ("brute", 6), ("sapper", 3), ("champion", 1)):
        for _ in range(count):
            m.creeps[uid] = GroundUnit(uid=uid, n=0, e=0, speed=0, kind=kind, gate=0)
            uid += 1
    m._report_spawn(world)  # FakeWorld enforces the 50-char law on the way out
    report = world.texts[-1][1]
    assert report.startswith("GAME: gate N: 5 grunt 6 runner 6 brute 3 sapper")
    assert len(report) <= 50


# ------------------------------------------------------------------ stats

def test_the_pilot_tally_counts_every_role():
    world, m = make()
    world.views = [view("d0", n=QUARRY[0], e=QUARRY[1], alt=2.0)]
    world.run(m, PICKUP_DWELL + 0.2)
    mine = m.stats.pilots["s-d0"]
    assert mine.ferried == 1 and m.pilot("s-d0")["detail"] == "f1"
    world.views = [hover((3, 1), alt=3.0)]
    world.run(m, PLACE_DWELL + 0.2)
    assert mine.placed == 1 and mine.detail == "f1 b1"
    add_creep(m, (0, 2))
    world.views = [hover((0, 2), alt=2.0)]
    world.run(m, ZAP_DWELL + 0.2)
    assert mine.zapped == 1 and mine.detail == "z1 f1 b1"
    assert m.stats.as_dict()["pilots"]["s-d0"] == mine.as_dict()
    assert PilotStats().detail == ""
    assert m.pilot("nobody")["detail"] == ""


def test_ferry_and_build_feed_rows_come_every_five():
    world, m = make()
    m.quarry.remaining = None  # ten pickups: more than the grace stock
    for _ in range(10):
        world.views = [view("d0", n=QUARRY[0], e=QUARRY[1], alt=2.0)]
        world.run(m, PICKUP_DWELL + 0.2)
        m.carry.clear()  # drop it: only the pickups matter here
    rows = [ev for ev in world.events if ev["kind"] == "ferried"]
    assert [ev["msg"] for ev in rows] == ["D0 ferried 5 tiles", "D0 ferried 10 tiles"]
    for i in range(5):
        m.carry.give("d0", "steel")
        cell = (3 + i, 1)
        world.views = [hover(cell, alt=3.0)]
        world.run(m, PLACE_DWELL + 0.2)
    built = [ev for ev in world.events if ev["kind"] == "built"]
    assert [ev["msg"] for ev in built] == ["D0 placed 5 tiles"]


def test_reset_clears_repairs_spotters_and_the_tally():
    world, m = make()
    chew(world, m, (3, 1))
    m.spotters[0] = "d0"
    m.stats.pilot("s-d0").ferried = 4
    m.wave = 2
    m.reset(world)
    assert not m.repairs and not m.spotters and m.stats.pilots == {}
