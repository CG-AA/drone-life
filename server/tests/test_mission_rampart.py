"""Rampart mission: the full ferry-and-build loop through the WorldAPI seam."""

from dataclasses import replace

from app.game import hex
from app.game.building import (
    HINT_SUSTAIN,
    PICKUP_DWELL,
    PLACE_DWELL,
    TOO_HIGH_SAY,
    hover_alt_hint,
)
from app.game.missions.rampart import (
    FERRY,
    PLACE_POINTS,
    QUARRY,
    WALL_BONUS,
    WALL_HEIGHT,
    RampartMission,
)
from tests.support.harness import FakeWorld, view


def make() -> tuple[RampartMission, FakeWorld]:
    world = FakeWorld()
    mission = RampartMission()
    world.start(mission)
    return mission, world


def pick_up(mission, world):
    world.views = [view(n=QUARRY[0], e=QUARRY[1], alt=2.0)]
    world.run(mission, PICKUP_DWELL + 0.2)


def place_at(mission, world, cell):
    n, e = hex.axial_to_world(cell)
    world.views = [view(n=n, e=e, alt=float(hover_alt_hint(mission.tm, cell)))]
    world.run(mission, PLACE_DWELL + 0.2)


def test_setup_announces_quarry_and_gap():
    mission, world = make()
    assert any("quarry at N -32 E 39" in t for target, t in world.texts if target == "*")
    assert any("wall gap at" in t and "hover 4" in t
               for target, t in world.texts if target == "*")
    kinds = [e.kind for e in mission.entities(world)]
    assert kinds.count("tile_source") == 1
    assert kinds.count("ghost_tile") == len(mission.targets)


def test_pickup_then_place_scores():
    mission, world = make()
    pick_up(mission, world)
    assert mission.carry.item("d0") == "steel"
    assert any("got steel" in t for target, t in world.texts if target == "d0")

    cell = mission.targets[0]
    place_at(mission, world, cell)
    assert mission.tm.height(cell) == 1
    assert world.score == PLACE_POINTS
    assert any("placed! wall 1/" in t for target, t in world.texts if target == "d0")
    assert mission.carry.item("d0") is None


def test_wrong_cell_is_refused_and_keeps_the_tile():
    mission, world = make()
    pick_up(mission, world)
    wrong = hex.world_to_axial(-40.0, -40.0)
    assert wrong not in mission.targets
    place_at(mission, world, wrong)
    assert mission.tm.height(wrong) == 0
    assert mission.carry.item("d0") == "steel"
    assert any("not a wall cell" in t for target, t in world.texts if target == "d0")


def test_carrier_crash_loses_the_tile():
    mission, world = make()
    pick_up(mission, world)
    world.views = [replace(view(), crashed=True, armed=False)]
    world.run(mission, 0.2)
    assert mission.carry.item("d0") is None
    assert any("steel lost" in t for target, t in world.texts if target == "*")


def test_completing_the_wall_pays_the_bonus():
    mission, world = make()
    for cell in mission.targets:
        for _ in range(WALL_HEIGHT):
            pick_up(mission, world)
            place_at(mission, world, cell)
    assert mission.built() == mission.total
    assert world.score == mission.total * PLACE_POINTS + WALL_BONUS
    assert mission.done
    assert any("rampart complete" in t for target, t in world.texts if target == "*")
    kinds = [e.kind for e in mission.entities(world)]
    assert kinds.count("ghost_tile") == 0, "no gaps left to show"


def test_quarry_and_pads_are_unbuildable():
    mission, _world = make()
    assert mission.tm.can_place(hex.world_to_axial(*QUARRY), "steel")[0] is False
    assert mission.tm.can_place(hex.pad_cell(0), "steel")[0] is False


def test_reset_rebuilds_the_same_map_object():
    mission, world = make()
    pick_up(mission, world)
    place_at(mission, world, mission.targets[0])
    tm = mission.tile_map()
    mission.reset(world)
    assert mission.tile_map() is tm
    assert mission.built() == 0
    assert mission.carry.item("d0") is None


def test_hands_full_at_the_quarry_hints():
    mission, world = make()
    pick_up(mission, world)  # d0 now carries steel, still hovering the quarry
    world.run(mission, HINT_SUSTAIN + 0.3)
    assert ("d0", FERRY.full_say) in world.texts


def test_too_high_at_the_quarry_hints():
    mission, world = make()
    world.views = [view(n=QUARRY[0], e=QUARRY[1], alt=12.0)]
    world.run(mission, HINT_SUSTAIN + 0.3)
    assert ("d0", TOO_HIGH_SAY) in world.texts
