"""Siege's second wave of buildings: the clay pit, the ring tower, the
beacon that lures, and the bell that freezes."""

from app.game import hex
from app.game.building import PICKUP_DWELL, PLACE_DWELL
from app.game.missions.siege import (
    BEACON_MAX,
    BEACON_RADIUS,
    BELL_DWELL_S,
    CHEW_S,
    FREEZE_S,
    KEEP_HP,
    LURE_BONUS_EACH,
    PIT,
    RING_COOLDOWN,
    RING_POINTS,
    RING_RANGE,
    TOWER_COOLDOWN,
    TOWER_RANGE,
    SiegeMission,
)
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, build_tower, freeze_waves, hover, texts


def make():
    world = FakeWorld()
    m = SiegeMission()
    world.start(m)
    freeze_waves(m)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    return world, m


def place(world, m, cell, material, drone_id="d0"):
    """One placement dwell of `material` onto `cell`."""
    m.carry.give(drone_id, material)
    before = m.tm.height(cell)
    world.views = [hover(cell, alt=2.0 * (before + 1) + 1.0, drone_id=drone_id)]
    world.run(m, PLACE_DWELL + 0.2)
    assert m.tm.height(cell) == before + 1, f"placement onto {cell} should commit"


def ring_of(centre, material, world, m):
    for cell in hex.ring(centre, 1):
        place(world, m, cell, material)


# --------------------------------------------------------------- clay pit

def test_the_pit_hands_out_clay_with_its_own_words():
    world, m = make()
    assert any("clay pit at N 50 E -44" in t for t in texts(world))
    world.views = [view("d0", n=PIT[0], e=PIT[1], alt=2.0)]
    world.run(m, PICKUP_DWELL + 0.2)
    assert m.carry.item("d0") == "clay"
    assert ("d0", "GAME: got clay, cheap walls, chewed 3x faster") in world.texts
    pit = next(e for e in m.entities(world) if e.id == "clay_pit")
    assert pit.data == {"material": "clay", "remaining": None}, "infinite"
    assert_grammar(world)


def test_clay_walls_are_chewed_three_times_faster():
    world, m = make()
    for wall in hex.ring((0, 0), 2):
        m.tm.place(wall, "clay")
        m.tm.place(wall, "clay")
    add_creep(m, (0, 4), speed=1.5)
    world.run(m, 20.0)  # ~7 s to the ring, a 2 s chew (6 s for steel), ~7 s in
    chews = [t for t in texts(world) if "chewed at" in t]
    assert chews and chews[0].startswith("GAME: clay chewed at"), "material in the warning"
    assert m.keep_hp == KEEP_HP - 1, "through and in; the steel ring needs 25 s"


# ------------------------------------------------------------- ring tower

def test_six_steel_around_a_watchtower_make_a_ring_tower_either_order():
    world, m = make()
    centre = (4, 1)
    build_tower(world, m, centre)
    before = world.score
    ring_of(centre, "steel", world, m)
    assert m.towers[centre].ring is True
    assert world.score == before + RING_POINTS and m.stats.ring_towers == 1
    assert any(t.startswith("GAME: ring tower at N") and t.endswith(f"! +{RING_POINTS}")
               for t in texts(world))
    tower = next(e for e in m.entities(world) if e.kind == "tower")
    assert tower.data == {"range": RING_RANGE, "tier": 0, "ring": True}
    # the other order: the ring first, the centre last
    centre2 = (-6, 3)
    ring_of(centre2, "steel", world, m)
    assert centre2 not in m.towers
    build_tower(world, m, centre2)
    assert m.towers[centre2].ring is True and m.stats.ring_towers == 2
    assert_grammar(world)


def test_a_ring_tower_reaches_far_and_reloads_fast():
    world, m = make()
    centre = (4, 1)
    build_tower(world, m, centre)
    ring_of(centre, "steel", world, m)
    tn, te = hex.axial_to_world(centre)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    far = add_creep(m, centre, uid=7)
    far.n, far.e = tn + (TOWER_RANGE + RING_RANGE) / 2, te  # 22 m: stock misses, ring hits
    world.run(m, 0.3)
    assert not m.creeps
    a = add_creep(m, (4, 3), uid=8)
    a.hp = 3
    world.run(m, RING_COOLDOWN * 3 + 0.3)
    assert not m.creeps, "three shots in three ring cooldowns (the stock tower needs 6 s)"
    assert m._tower_stats(m.towers[centre])[1] == RING_COOLDOWN < TOWER_COOLDOWN


def test_chewing_the_ring_drops_it_to_a_watchtower_and_it_can_be_rebuilt():
    world, m = make()
    centre = (4, 1)
    build_tower(world, m, centre)
    ring_of(centre, "steel", world, m)
    lost = hex.ring(centre, 1)[2]
    m.tm.remove_top(lost)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    world.run(m, 0.2)
    assert m.towers[centre].ring is False and centre in m.towers
    assert any(t.startswith("GAME: ring lost at N") and t.endswith("watchtower again")
               for t in texts(world))
    place(world, m, lost, "steel")
    assert m.towers[centre].ring is True, "rebuildable: the claims were released"
    assert_grammar(world)


# ----------------------------------------------------------------- beacon

def make_beacon(world, m, anchor):
    left, right = hex.add(anchor, (1, 0)), hex.add(anchor, (-1, 0))
    place(world, m, left, "clay")
    place(world, m, right, "clay")
    place(world, m, anchor, "steel")
    return anchor


def test_a_clay_steel_clay_line_is_a_beacon_that_lures_nearby_creeps():
    world, m = make()
    anchor = make_beacon(world, m, (6, 0))  # ~N 0 E 31
    assert anchor in m.beacons
    assert any(t.startswith("GAME: beacon up at N") and t.endswith("creeps lured")
               for t in texts(world))
    an, ae = hex.axial_to_world(anchor)
    world.views = [view("d0", n=-90.0, e=-76.0)]
    near = add_creep(m, (8, 0), uid=1, speed=2.0)  # ~10 m from the beacon, 41 m from the Keep
    far = add_creep(m, (0, 12), uid=2, speed=2.0)  # 54 m north: marches on
    world.run(m, 4.0)
    assert 1 in m.lured and 2 not in m.lured
    assert abs(near.n - an) + abs(near.e - ae) < abs(hex.axial_to_world((8, 0))[1] - ae), "closer"
    assert far.n < hex.axial_to_world((0, 12))[0], "the far one still walks to the Keep"
    beacon = next(e for e in m.entities(world) if e.kind == "beacon")
    assert beacon.data["radius"] == BEACON_RADIUS and beacon.data["lured"] == 1
    assert_grammar(world)


def test_lured_creeps_eat_the_beacon_and_then_resume_and_kills_pay_extra():
    world, m = make()
    anchor = make_beacon(world, m, (6, 0))
    world.views = [view("d0", n=-90.0, e=-76.0)]
    add_creep(m, (7, 0), uid=1, speed=3.0)
    world.run(m, 4.0 + CHEW_S + 0.5)
    assert anchor not in m.beacons and m.tm.height(anchor) == 0
    assert any(t.startswith("GAME: beacon chewed at") for t in texts(world))
    assert 1 not in m.lured and m.creeps, "it walks on toward the Keep"
    # the clay ends still stand: one steel relights it, and a zap on a lured
    # creep pays the pool extra
    place(world, m, anchor, "steel")
    assert anchor in m.beacons, "the chewed beacon's claims were released"
    pool = m.pool
    add_creep(m, (7, 0), uid=2, speed=0.0)
    cn, ce = hex.axial_to_world((7, 0))
    world.views = [view("d0", n=cn, e=ce, alt=2.0)]
    world.run(m, 2.0)
    assert 2 not in m.creeps
    assert m.pool == pool + 1 + LURE_BONUS_EACH, "one seat: a coin, plus the lure bonus"


def test_at_most_two_beacons_stand():
    world, m = make()
    make_beacon(world, m, (6, 0))
    make_beacon(world, m, (-6, 0))
    make_beacon(world, m, (0, 6))
    assert len(m.beacons) == BEACON_MAX


# ------------------------------------------------------------------- bell

def make_bell(world, m, centre=(-4, 2)):
    ring_of(centre, "clay", world, m)
    for _ in range(3):
        place(world, m, centre, "clay")
    return centre


def test_a_hover_on_the_bell_freezes_every_creep_and_spends_the_bell():
    world, m = make()
    centre = make_bell(world, m)
    assert centre in m.bells
    hint = next(t for t in texts(world) if t.startswith("GAME: bell up at N"))
    assert hint.endswith("hover 8 m to ring")
    bell = next(e for e in m.entities(world) if e.kind == "bell")
    assert bell.data["hover"] == 8 and 0 <= bell.data["charge"] < 0.5
    creep = add_creep(m, (0, 6), uid=1, speed=2.0)
    n0 = creep.n
    cn, ce = hex.axial_to_world(centre)
    world.views = [view("d0", n=cn, e=ce, alt=4.0)]  # inside the stack: no
    world.run(m, BELL_DWELL_S + 0.3)
    assert centre in m.bells
    world.views = [view("d0", n=cn, e=ce, alt=8.0)]
    world.run(m, BELL_DWELL_S + 0.2)
    assert centre not in m.bells and m.tm.height(centre) == 0 and m.stats.bells == 1
    assert all(m.tm.height(c) == 0 for c in hex.ring(centre, 1)), "spent"
    assert ("*", "GAME: bell rung! creeps frozen 15 s") in world.texts
    assert m.hud()["frozen_s"] == 15 or m.hud()["frozen_s"] == 14
    frozen_at = creep.n
    world.run(m, FREEZE_S - 1.0)
    assert creep.n == frozen_at and creep.n < n0, "it had walked, then stood still"
    troop = next(e for e in m.entities(world) if e.kind == "troop")
    assert troop.data["frozen"] is True
    world.run(m, 2.0)
    assert creep.n < frozen_at, "and walks again"
    assert any(ev["kind"] == "bell_rung" for ev in world.events)
    assert_grammar(world)


def test_towers_keep_shooting_while_creeps_are_frozen():
    world, m = make()
    build_tower(world, m, (4, 1))
    m.freeze_s = FREEZE_S
    world.views = [view("d0", n=-90.0, e=-76.0)]
    add_creep(m, (4, 3), uid=1)
    world.run(m, 0.3)
    assert not m.creeps


def test_structures_do_not_share_cells():
    """A bell's ring cell cannot double as a beacon's clay end."""
    world, m = make()
    centre = make_bell(world, m)
    ring = hex.ring(centre, 1)
    # a steel single next to a ring cell, with that ring cell as one clay end
    # and a fresh clay on the other side: the ring cell is claimed, no beacon
    end = ring[0]
    steel = hex.add(end, (1, 0))
    other = hex.add(steel, (1, 0))
    place(world, m, other, "clay")
    place(world, m, steel, "steel")
    assert steel not in m.beacons


def test_reset_clears_every_structure():
    world, m = make()
    build_tower(world, m, (4, 1))
    ring_of((4, 1), "steel", world, m)
    make_beacon(world, m, (6, 0))
    make_bell(world, m)
    m.freeze_s, m.wave = 5.0, 2
    m.reset(world)
    assert not m.towers and not m.beacons and not m.bells and m.freeze_s == 0
    assert not m.ring_bps.claimed and not m.beacon_bps.claimed and not m.bell_bps.claimed
    assert m.hud()["frozen_s"] == 0
