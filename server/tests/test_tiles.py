"""TileMap rules: stacks, bounds, keep-out, version signal, terrain seam."""

from app.game import hex
from app.game.tiles import MAX_STACK, TILE_HEIGHT, TileMap
from app.sim.terrain import Terrain


def test_place_and_stack_queries():
    tm = TileMap()
    assert tm.place((0, 0), "steel") == (True, "")
    assert tm.place((0, 0), "clay") == (True, "")
    assert tm.stack((0, 0)) == ("steel", "clay")
    assert tm.top((0, 0)) == "clay"
    assert tm.height((0, 0)) == 2
    assert tm.top_alt((0, 0)) == 2 * TILE_HEIGHT
    assert list(tm.cells()) == [((0, 0), ("steel", "clay"))]


def test_remove_top_and_clear():
    tm = TileMap()
    tm.place((1, 1), "steel")
    tm.place((1, 1), "clay")
    assert tm.remove_top((1, 1)) == "clay"
    assert tm.remove_top((1, 1)) == "steel"
    assert tm.remove_top((1, 1)) is None
    assert tm.height((1, 1)) == 0
    tm.place((2, 2), "steel")
    tm.clear()
    assert list(tm.cells()) == []


def test_rejections():
    tm = TileMap()
    assert tm.place((0, 0), "gold")[0] is False
    far = hex.world_to_axial(150.0, 0.0)  # outside the arena
    assert tm.place(far, "steel") == (False, "outside the arena")
    for _ in range(MAX_STACK):
        assert tm.place((3, 3), "steel")[0] is True
    assert tm.place((3, 3), "steel") == (False, "stack is full")


def test_keep_out_rejects_near_pads():
    tm = TileMap()
    pad = hex.pad_position(0)
    tm.set_keep_out([pad], radius=6.0)
    near = hex.world_to_axial(*pad)
    assert tm.place(near, "steel") == (False, "too close to a pad")
    far = hex.world_to_axial(pad[0] + 20, pad[1])
    assert tm.place(far, "steel")[0] is True


def test_version_bumps_only_on_mutation():
    tm = TileMap()
    v0 = tm.version
    assert tm.place((0, 0), "gold")[0] is False  # rejected: no bump
    assert tm.version == v0
    tm.place((0, 0), "steel")
    assert tm.version == v0 + 1
    assert tm.remove_top((5, 5)) is None  # nothing there: no bump
    assert tm.version == v0 + 1
    tm.clear()
    assert tm.version == v0 + 2


def test_height_at_matches_cells_and_is_zero_elsewhere():
    tm = TileMap()
    tm.place((2, -1), "steel")
    tm.place((2, -1), "steel")
    n, e = hex.axial_to_world((2, -1))
    assert tm.height_at(n, e) == 2 * TILE_HEIGHT
    inradius = hex.HEX_SIZE * hex.SQRT3 / 2
    assert tm.height_at(n, e + 0.9 * inradius) == 2 * TILE_HEIGHT  # still inside the hex
    assert tm.height_at(n, e + 2 * inradius) == 0.0  # neighbor cell is empty
    assert tm.height_at(50.0, 50.0) == 0.0


def test_tilemap_satisfies_terrain_protocol():
    assert isinstance(TileMap(), Terrain)


def test_pathability_queries():
    tm = TileMap()
    tm.place((0, 0), "steel")
    assert tm.blocked((0, 0)) is True
    assert tm.blocked((1, 0)) is False
    # from flat ground next to a 1-stack: can't climb at 0, can at 1
    assert (0, 0) not in tm.passable_neighbors((1, 0), climb=0)
    assert (0, 0) in tm.passable_neighbors((1, 0), climb=1)
    assert all(tm.in_bounds(c) for c in tm.passable_neighbors((1, 0), climb=1))


def test_to_wire_shape():
    tm = TileMap()
    tm.place((1, -2), "clay")
    tm.place((1, -2), "clay")
    wire = tm.to_wire()
    assert wire["geometry"] == {"size": hex.HEX_SIZE, "tile_height": TILE_HEIGHT}
    assert wire["cells"] == [{"q": 1, "r": -2, "stack": ["clay", "clay"]}]
