"""Canyon mission: pre-placed walls through the WorldAPI seam."""

from app.game.missions.canyon import WALL_E, WALL_HEIGHT, CanyonMission
from tests.conftest import FakeWorld


def make() -> tuple[CanyonMission, FakeWorld]:
    world = FakeWorld()
    mission = CanyonMission()
    mission.setup(world)
    return mission, world


def test_setup_builds_two_walls():
    mission, world = make()
    cells = dict(mission.tm.cells())
    assert len(cells) > 20, "two 80 m walls are many cells"
    assert all(stack == ("steel",) * WALL_HEIGHT for stack in cells.values())
    # each wall blocks a crossing at mid-height: a hex line zigzags around the
    # straight segment, so probe a window around the nominal e instead of a point
    for e0 in WALL_E:
        assert any(mission.tm.height_at(0.0, e0 + d / 2) == WALL_HEIGHT * 2.0
                   for d in range(-6, 7)), f"wall at e={e0} has a gap at n=0"
    # the corridor between the walls is clear
    assert mission.tm.height_at(0.0, (WALL_E[0] + WALL_E[1]) / 2) == 0.0
    assert any("canyon walls up" in t for target, t in world.texts if target == "*")


def test_tile_map_identity_is_stable_across_reset():
    mission, world = make()
    tm = mission.tile_map()
    assert tm is mission.tm
    cells_before = set(dict(tm.cells()))
    version_before = tm.version
    mission.reset(world)
    assert mission.tile_map() is tm, "reset rebuilds, never replaces"
    assert set(dict(tm.cells())) == cells_before, "same layout after reset"
    assert tm.version > version_before, "mutations bumped the broadcast signal"
