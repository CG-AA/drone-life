"""Flow field: every in-bounds cell gets a next step; walls price in chewing."""

from app.game import hex, path
from app.game.tiles import TileMap

GOAL = (0, 0)


def walk(field, start, limit=200):
    """Follow next_step from start; return the list of cells visited."""
    cells = [start]
    while cells[-1] != field.goal:
        nxt = field.toward(cells[-1])
        assert nxt is not None, f"no step out of {cells[-1]}"
        cells.append(nxt)
        assert len(cells) <= limit, "walk did not terminate"
    return cells


def stack(tm, cell, material, height):
    for _ in range(height):
        ok, why = tm.place(cell, material)
        assert ok, why


# ------------------------------------------------------------------ open map

def test_open_map_field_is_hex_distance():
    field = path.flood(TileMap(), GOAL, climb=1)
    for cell in [(5, 0), (-3, 7), (10, -10), (0, 17)]:
        assert field.cost[cell] == hex.distance(cell, GOAL)
        assert len(walk(field, cell)) == hex.distance(cell, GOAL) + 1


def test_field_covers_the_whole_arena_and_nothing_more():
    tm = TileMap()
    field = path.flood(tm, GOAL, climb=1)
    inside, outside = (0, 12), (0, 999)
    assert tm.in_bounds(inside) and field.has(inside)
    assert not tm.in_bounds(outside) and not field.has(outside)
    assert field.toward(GOAL) is None, "the goal has no next step"


# --------------------------------------------------------------------- walls

def test_one_high_wall_is_free_at_climb_one():
    tm = TileMap()
    for q in range(-6, 7):
        stack(tm, (q, 3), "steel", 1)
    field = path.flood(tm, GOAL, climb=1)
    start = (0, 6)
    assert field.cost[start] == hex.distance(start, GOAL), "climbable = open"


def test_two_high_wall_reroutes_without_chewing():
    tm = TileMap()
    for q in range(-5, 6):
        stack(tm, (q, 3), "steel", 2)
    field = path.flood(tm, GOAL, climb=1)
    start = (0, 6)
    assert field.cost[start] > hex.distance(start, GOAL), "the wall costs"
    cells = walk(field, start)
    for a, b in zip(cells, cells[1:], strict=False):
        assert abs(tm.height(a) - tm.height(b)) <= 1, "route never over-climbs"


def test_full_ring_routes_through_exactly_one_breach():
    tm = TileMap()
    for cell in hex.ring(GOAL, 2):
        stack(tm, cell, "steel", 2)
    field = path.flood(tm, GOAL, climb=1)
    start = (0, 5)  # distance 5, fully enclosed goal
    up_and_down = 2 * path.CHEW_COST  # climb onto the ring + drop off it
    assert field.cost[start] == hex.distance(start, GOAL) + up_and_down
    cells = walk(field, start)
    on_wall = [c for c in cells if tm.height(c) == 2]
    assert len(on_wall) == 1, "crosses the ring through a single breach cell"


def test_wall_tops_are_on_the_field():
    tm = TileMap()
    wall = (0, 3)
    stack(tm, wall, "steel", 2)
    field = path.flood(tm, GOAL, climb=1)
    assert field.has(wall), "a unit marooned on a stack still has a plan"


# ------------------------------------------------------------------ plumbing

def test_flood_is_deterministic():
    tm = TileMap()
    for cell in [(2, 2), (3, 2), (-4, 0)]:
        stack(tm, cell, "clay", 2)
    a = path.flood(tm, GOAL, climb=1)
    b = path.flood(tm, GOAL, climb=1)
    assert a.next_step == b.next_step
    assert a.cost == b.cost
