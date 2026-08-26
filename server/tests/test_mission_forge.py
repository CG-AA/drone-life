"""Forge mission: free placement, blueprint matching, furnaces from data."""

from app.game import hex
from app.game.building import HINT_SUSTAIN, PICKUP_DWELL, PLACE_DWELL, hover_alt_hint
from app.game.missions.forge import (
    CLAY_PIT,
    FERRY,
    FURNACE_POINTS,
    PLACE_POINTS,
    ForgeMission,
)
from tests.support.harness import FakeWorld, view


def make() -> tuple[ForgeMission, FakeWorld]:
    world = FakeWorld()
    mission = ForgeMission()
    world.start(mission)
    return mission, world


def carry_one_to(mission, world, cell):
    world.views = [view(n=CLAY_PIT[0], e=CLAY_PIT[1], alt=2.0)]
    world.run(mission, PICKUP_DWELL + 0.2)
    assert mission.carry.item("d0") == "clay"
    n, e = hex.axial_to_world(cell)
    world.views = [view(n=n, e=e, alt=float(hover_alt_hint(mission.tm, cell)))]
    world.run(mission, PLACE_DWELL + 0.2)


def ring_cells(center):
    return [hex.add(center, off) for off in hex.ring((0, 0), 1)]


def test_five_ring_tiles_do_not_light_a_furnace():
    mission, world = make()
    for cell in ring_cells((0, 0))[:5]:
        carry_one_to(mission, world, cell)
    assert mission.furnaces == []
    assert world.score == 5 * PLACE_POINTS


def test_sixth_tile_lights_the_furnace():
    mission, world = make()
    cells = ring_cells((0, 0))
    for cell in cells:
        carry_one_to(mission, world, cell)
    assert mission.furnaces == [(0, 0)], "the furnace sits at the ring center"
    assert world.score == 6 * PLACE_POINTS + FURNACE_POINTS
    assert any("furnace lit" in t for target, t in world.texts if target == "*")
    kinds = [e.kind for e in mission.entities(world)]
    assert kinds.count("furnace") == 1
    assert kinds.count("tile_source") == 1


def test_second_disjoint_ring_lights_a_second_furnace():
    mission, world = make()
    for cell in ring_cells((0, 0)):
        carry_one_to(mission, world, cell)
    for cell in ring_cells((10, -3)):
        carry_one_to(mission, world, cell)
    assert len(mission.furnaces) == 2
    assert world.score == 12 * PLACE_POINTS + 2 * FURNACE_POINTS


def test_reset_clears_furnaces_and_claims():
    mission, world = make()
    for cell in ring_cells((0, 0)):
        carry_one_to(mission, world, cell)
    mission.reset(world)
    assert mission.furnaces == []
    assert mission.blueprints.claimed == set()
    assert list(mission.tm.cells()) == []
    # the same ring lights again after a reset
    for cell in ring_cells((0, 0)):
        carry_one_to(mission, world, cell)
    assert len(mission.furnaces) == 1


def test_hands_full_at_the_pit_hints():
    mission, world = make()
    world.views = [view(n=CLAY_PIT[0], e=CLAY_PIT[1], alt=2.0)]
    world.run(mission, PICKUP_DWELL + 0.2)
    assert mission.carry.item("d0") == "clay"
    world.run(mission, HINT_SUSTAIN + 0.3)  # still hovering the pit, hands full
    assert ("d0", FERRY.full_say) in world.texts
