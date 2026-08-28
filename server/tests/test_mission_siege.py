"""Siege mission through the WorldAPI seam: waves, combat verbs, keep, towers."""

from app.game import hex
from app.game.building import HINT_SUSTAIN, PICKUP_DWELL, PLACE_DWELL
from app.game.missions.siege import (
    BEAM_S,
    FERRY,
    GRACE_S,
    KEEP_FALL_POINTS,
    KEEP_HP,
    KILL_POINTS,
    POOF_S,
    QUARRY,
    TOWER_POINTS,
    WAVE_BONUS,
    ZAP_ARC_S,
    ZAP_DWELL,
    SiegeMission,
)
from app.game.units import GroundUnit
from tests.support.harness import FakeWorld, assert_grammar, view


def make():
    world = FakeWorld()
    mission = SiegeMission()
    world.start(mission)
    return world, mission


def freeze_waves(m):
    """Park the wave machine so combat tests control the creep roster."""
    m.state, m.timer = "build", 1e9


def add_creep(m, cell, uid=1, speed=0.0):
    n, e = hex.axial_to_world(cell)
    m.creeps[uid] = GroundUnit(uid=uid, n=n, e=e, speed=speed)
    return m.creeps[uid]


def hover(cell, alt, drone_id="d0"):
    n, e = hex.axial_to_world(cell)
    return view(drone_id, n=n, e=e, alt=alt)


def place_tile(world, m, cell, drone_id="d0"):
    """Drive one full placement dwell onto `cell` by a steel-carrying drone."""
    m.carry.give(drone_id, "steel")
    before = m.tm.height(cell)
    world.views = [hover(cell, alt=2.0 * (before + 1) + 1.0, drone_id=drone_id)]
    world.run(m, PLACE_DWELL + 0.2)
    assert m.tm.height(cell) == before + 1, "placement dwell should commit"


def texts(world):
    return [text for _target, text in world.texts]


# ------------------------------------------------------------ setup & waves

def test_setup_entities_and_announcements():
    world, m = make()
    kinds = {e.kind for e in m.entities(world)}
    assert {"keep", "tile_source"} <= kinds
    keep = next(e for e in m.entities(world) if e.kind == "keep")
    assert keep.data == {"hp": KEEP_HP, "max": KEEP_HP}
    assert any("keep at N 0 E 0" in t for t in texts(world))
    assert any("quarry at N -50 E 44" in t for t in texts(world))
    assert_grammar(world)


def test_wave_starts_after_grace_with_a_drone_present():
    world, m = make()
    world.views = [view("d0", n=-90.0, e=-76.0)]
    world.run(m, GRACE_S + 1.0)
    assert m.state == "active" and m.wave == 1
    assert len(m.creeps) >= 1, "creeps spawning from the gate"
    assert any("wave 1 at N" in t and "4 creeps" in t for t in texts(world))
    assert_grammar(world)


def test_hud_state_tracks_the_wave_machine():
    world, m = make()
    assert m.hud() == {"wave": 0, "state": "grace", "timer_s": 45, "keep_hp": KEEP_HP,
                       "keep_max": KEEP_HP, "creeps_alive": 0, "pending": 0, "towers": 0}
    world.views = [view("d0", n=-90.0, e=-76.0)]
    world.run(m, 10.0)
    assert m.hud()["timer_s"] == 35 and m.hud()["state"] == "grace"
    world.run(m, GRACE_S - 10.0 + 0.5)
    h = m.hud()
    assert h["wave"] == 1 and h["state"] == "active" and h["timer_s"] == 0
    assert h["creeps_alive"] + h["pending"] == 4
    assert all(isinstance(v, int) for k, v in h.items() if k != "state"), "integers only"


def test_empty_room_freezes_the_clock():
    world, m = make()
    world.run(m, GRACE_S + 10.0)
    assert m.state == "grace" and not m.creeps, "no drones, no siege"


def test_wave_clear_pays_and_schedules_the_next():
    world, m = make()
    world.views = [view("d0")]
    m.state, m.wave, m.pending = "active", 1, 0
    before = world.score
    world.run(m, 0.3)
    assert world.score == before + WAVE_BONUS
    assert m.state == "build"
    assert any("wave 1 clear! +10" in t for t in texts(world))
    assert any("wave 2 in 20s, build!" in t for t in texts(world))
    world.run(m, 21.0)
    assert m.state == "active" and m.wave == 2
    assert_grammar(world)


# ------------------------------------------------------------- keep damage

def test_march_hits_the_keep():
    world, m = make()
    freeze_waves(m)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    add_creep(m, (0, 2), speed=2.0)
    world.run(m, 8.0)
    assert m.keep_hp == KEEP_HP - 1
    assert not m.creeps, "the creep died on arrival"
    assert any("keep hit! hp 9" in t for t in texts(world))
    assert_grammar(world)


def test_keep_fall_costs_points_and_rebuilds():
    world, m = make()
    freeze_waves(m)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    m.keep_hp = 1
    add_creep(m, (0, 2), speed=2.0)
    before = world.score
    world.run(m, 8.0)
    assert world.score == before + KEEP_FALL_POINTS
    assert m.keep_hp == KEEP_HP, "restored at full hp"
    assert any("keep fell! -25, rebuilt" in t for t in texts(world))
    assert_grammar(world)


# ------------------------------------------------------------ combat verbs

def test_zap_kill():
    world, m = make()
    freeze_waves(m)
    creep = add_creep(m, (4, 0))
    world.views = [view("d0", n=creep.n, e=creep.e, alt=2.0)]
    before = world.score
    world.run(m, 2.0)
    assert not m.creeps
    assert world.score == before + KILL_POINTS
    assert ("d0", f"GAME: zap! creep down +{KILL_POINTS}") in world.texts
    assert_grammar(world)


def test_squish_kill_commits_the_tile():
    world, m = make()
    freeze_waves(m)
    cell = (4, 1)
    add_creep(m, cell)
    before = world.score
    place_tile(world, m, cell)
    assert m.tm.stack(cell) == ("steel",)
    assert not m.creeps, "the tile landed on it"
    assert world.score == before + KILL_POINTS
    assert any("squish! creep under tile" in t for t in texts(world))
    assert any("placed! tile at" in t for t in texts(world))
    assert_grammar(world)


# ------------------------------------------------------------------ towers

def build_tower(world, m, cell):
    for _ in range(3):
        place_tile(world, m, cell)


def test_tower_builds_fires_and_beam_expires():
    world, m = make()
    freeze_waves(m)
    cell = (4, 1)
    before = world.score
    build_tower(world, m, cell)
    assert cell in m.towers
    assert world.score == before + TOWER_POINTS
    assert any("tower up! +15" in t for t in texts(world))
    placed = [t for t in texts(world) if "placed! tile at" in t]
    assert len(placed) == 2, "the tower-completing tile gets the tower text"

    creep = add_creep(m, (4, 3))  # two cells out: ~10.4 m, inside range
    tn, te = hex.axial_to_world(cell)
    assert ((creep.n - tn) ** 2 + (creep.e - te) ** 2) ** 0.5 <= 12.0
    world.run(m, 0.3)
    assert not m.creeps, "the tower shot it"
    beams = [e for e in m.entities(world) if e.kind == "beam"]
    assert len(beams) == 1 and beams[0].data["talt"] == creep.alt
    world.run(m, BEAM_S + 0.2)
    assert not [e for e in m.entities(world) if e.kind == "beam"], "beam expired"
    assert_grammar(world)


def test_tower_kill_credits_the_builder_silently():
    world, m = make()
    freeze_waves(m)
    build_tower(world, m, (4, 1))
    assert m.towers[(4, 1)].builder == "s-d0"
    world.events.clear()
    add_creep(m, (4, 3))
    world.run(m, 0.3)
    assert not m.creeps
    assert world.scores[-1] == (KILL_POINTS, "tower kill", "s-d0")
    assert m.towers[(4, 1)].kills == 1
    assert [ev["kind"] for ev in world.events] == [], "tower shots never post feed rows"


def test_tower_up_and_wave_clear_post_one_feed_row_each():
    world, m = make()
    freeze_waves(m)
    world.events.clear()
    build_tower(world, m, (4, 1))
    kinds = [ev["kind"] for ev in world.events]
    assert kinds.count("tower_up") == 1 and "score" not in kinds
    assert any("+15" in ev["msg"] for ev in world.events if ev["kind"] == "tower_up")
    world.events.clear()
    world.views = [view("d0")]
    m.state, m.wave, m.pending = "active", 1, 0
    world.run(m, 0.3)
    kinds = [ev["kind"] for ev in world.events]
    assert kinds == ["wave_clear"], kinds


def test_tower_dies_when_chewed_and_is_rebuildable():
    world, m = make()
    freeze_waves(m)
    cell = (4, 1)
    build_tower(world, m, cell)
    m.tm.remove_top(cell)  # what a creep chew does
    world.run(m, 0.2)
    assert cell not in m.towers
    assert cell not in m.blueprints.claimed, "claim released"
    assert any("tower down at" in t for t in texts(world))
    place_tile(world, m, cell)  # stack back to 3
    assert cell in m.towers, "rebuilt tower re-arms"
    assert_grammar(world)


# ---------------------------------------------------------------- chewing

def test_creep_chews_through_a_full_ring():
    world, m = make()
    freeze_waves(m)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    for wall in hex.ring((0, 0), 2):
        m.tm.place(wall, "steel")
        m.tm.place(wall, "steel")
    add_creep(m, (0, 4), speed=1.5)
    world.run(m, 25.0)
    assert any("wall chewed at" in t for t in texts(world))
    assert m.keep_hp == KEEP_HP - 1, "enclosure delays, never stops"
    assert_grammar(world)


# ------------------------------------------------------------------- reset

def test_reset_keeps_tile_map_identity():
    world, m = make()
    tm = m.tile_map()
    m.tm.place((4, 1), "steel")
    add_creep(m, (0, 3))
    m.keep_hp = 3
    m.reset(world)
    assert m.tile_map() is tm, "same map object, rebuilt"
    assert not list(tm.cells()) and not m.creeps
    assert m.keep_hp == KEEP_HP and m.state == "grace"


# ------------------------------------------------------------------- beams

def test_beams_expire_even_in_an_empty_room():
    world, m = make()
    freeze_waves(m)
    m.beams.append(("beam1", world.now + BEAM_S, (0.0, 0.0, 5.0), (1.0, 1.0, 0.0)))
    world.views = []  # everyone left while a tower was mid-shot
    world.run(m, BEAM_S + 1.0)
    assert m.beams == []
    assert not [e for e in m.entities(world) if e.kind == "beam"]


def fx_kinds(world, m):
    return sorted(e.kind for e in m.entities(world) if e.kind in ("zap_arc", "poof"))


def test_zap_leaves_an_arc_and_a_poof_that_expire():
    world, m = make()
    freeze_waves(m)
    creep = add_creep(m, (4, 0))
    world.views = [view("d0", n=creep.n, e=creep.e, alt=2.0)]
    world.run(m, ZAP_DWELL + 0.15)  # the arc lives 0.3 s: look right after the kill
    assert not m.creeps
    assert fx_kinds(world, m) == ["poof", "zap_arc"]
    arc = next(e for e in m.entities(world) if e.kind == "zap_arc")
    assert (arc.n, arc.e, arc.alt) == (creep.n, creep.e, 2.0), "arc starts at the drone"
    assert (arc.data["tn"], arc.data["te"]) == (creep.n, creep.e), "…and ends at the creep"
    poof = next(e for e in m.entities(world) if e.kind == "poof")
    assert poof.data == {"verb": "zap"}
    world.run(m, max(POOF_S, ZAP_ARC_S) + 0.2)
    assert fx_kinds(world, m) == [], "cosmetics expire"


def test_squish_tower_and_leak_kills_each_poof_with_their_verb():
    world, m = make()
    freeze_waves(m)
    add_creep(m, (4, 1))
    place_tile(world, m, (4, 1))
    assert [e.data["verb"] for e in m.entities(world) if e.kind == "poof"] == ["squish"]
    world.run(m, POOF_S + 0.2)

    build_tower(world, m, (4, 1))
    add_creep(m, (4, 3), uid=2)
    world.run(m, 0.3)
    assert [e.data["verb"] for e in m.entities(world) if e.kind == "poof"] == ["tower"]
    world.run(m, POOF_S + 0.2)

    world.views = [view("d0", n=-90.0, e=-76.0)]
    add_creep(m, (0, 1), uid=3, speed=3.0)
    for _ in range(50):
        world.run(m, 0.1)
        if m.keep_hp < KEEP_HP:
            break
    assert m.keep_hp == KEEP_HP - 1
    assert [e.data["verb"] for e in m.entities(world) if e.kind == "poof"] == ["leak"]


def test_fx_expire_even_in_an_empty_room():
    world, m = make()
    freeze_waves(m)
    m._fx(world, "poof", 0.0, 0.0, 0.0, POOF_S, {"verb": "zap"})
    world.views = []  # everyone left mid-poof
    world.run(m, POOF_S + 1.0)
    assert m.fx == []
    assert fx_kinds(world, m) == []


def test_fx_ids_are_unique_across_a_burst():
    world, m = make()
    freeze_waves(m)
    for i in range(4):
        add_creep(m, (4, 0), uid=10 + i)
    world.views = [hover((4, 0), alt=2.0)]
    world.run(m, 2.0)  # one dwell kills every creep sharing the circle
    ids = [e.id for e in m.entities(world)]
    assert len(ids) == len(set(ids))


def test_hands_full_at_the_quarry_hints():
    world, m = make()
    freeze_waves(m)
    world.views = [view(n=QUARRY[0], e=QUARRY[1], alt=2.0)]
    world.run(m, PICKUP_DWELL + 0.2)
    assert m.carry.item("d0") == "steel"
    world.run(m, HINT_SUSTAIN + 0.3)  # still hovering the quarry, hands full
    assert ("d0", FERRY.full_say) in world.texts
    assert_grammar(world)
