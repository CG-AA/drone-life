"""Blueprint matching: anchored, rotation-invariant, claim-deduped."""

from app.game import hex
from app.game.blueprints import (
    Blueprint,
    BlueprintTracker,
    Requirement,
    find_match,
    pre_place,
    ring_blueprint,
)
from app.game.tiles import TileMap

RING = ring_blueprint("furnace", "clay", radius=1)
L_SHAPE = Blueprint("ell", (
    Requirement(0, 0, "steel"),
    Requirement(1, 0, "steel"),
    Requirement(0, 1, "steel"),
))


def test_ring_blueprint_geometry():
    assert len(RING.reqs) == 6
    assert {(r.dq, r.dr) for r in RING.reqs} == set(hex.ring((0, 0), 1))
    assert all(r.material == "clay" and r.height == 1 for r in RING.reqs)


def test_ring_matches_on_sixth_tile_only():
    tm = TileMap()
    center = (5, 2)
    cells = [hex.add(center, off) for off in hex.ring((0, 0), 1)]
    for cell in cells[:5]:
        assert tm.place(cell, "clay")[0]
        assert find_match(tm, RING, cell) is None
    assert tm.place(cells[5], "clay")[0]
    match = find_match(tm, RING, cells[5])
    assert match is not None
    assert match.anchor == center
    assert set(match.cells) == set(cells)


def test_unrelated_placement_does_not_match():
    tm = TileMap()
    center = (5, 2)
    for off in list(hex.ring((0, 0), 1))[:5]:
        tm.place(hex.add(center, off), "clay")
    far = (15, -8)
    tm.place(far, "clay")
    assert find_match(tm, RING, far) is None, "anchored search never scans the map"


def test_wrong_top_material_does_not_match():
    tm = TileMap()
    center = (0, 0)
    cells = [hex.add(center, off) for off in hex.ring((0, 0), 1)]
    for cell in cells:
        tm.place(cell, "clay")
    tm.place(cells[0], "steel")  # buried the clay
    assert find_match(tm, RING, cells[-1]) is None


def test_rotation_invariance_of_asymmetric_pattern():
    for rotation in range(6):
        tm = TileMap()
        anchor = (3, -1)
        placed = None
        for req in L_SHAPE.reqs:
            placed = hex.add(anchor, hex.rotate60((req.dq, req.dr), rotation))
            assert tm.place(placed, "steel")[0]
        match = find_match(tm, L_SHAPE, placed)
        assert match is not None, f"rotation {rotation} must match"


def test_requirement_height_needs_a_stack():
    bp = Blueprint("pillar", (Requirement(0, 0, "steel", height=2),))
    tm = TileMap()
    tm.place((0, 0), "steel")
    assert find_match(tm, bp, (0, 0)) is None
    tm.place((0, 0), "steel")
    assert find_match(tm, bp, (0, 0)) is not None


def test_tracker_claims_and_allows_disjoint_second():
    tm = TileMap()
    tracker = BlueprintTracker([RING])

    def build_ring(center):
        last = None
        for off in hex.ring((0, 0), 1):
            last = hex.add(center, off)
            tm.place(last, "clay")
        return last

    first = tracker.check(tm, build_ring((0, 0)))
    assert first is not None
    assert tracker.check(tm, first.cells[0]) is None, "claimed cells never re-match"
    second = tracker.check(tm, build_ring((10, -3)))
    assert second is not None
    assert set(second.cells).isdisjoint(first.cells)
    tracker.reset()
    assert tracker.claimed == set()


def test_pre_place_builds_the_pattern():
    tm = TileMap()
    cells = pre_place(tm, RING, (4, 4))
    assert len(cells) == 6
    for cell in cells:
        assert tm.stack(cell) == ("clay",)
    assert find_match(tm, RING, cells[0]) is not None
