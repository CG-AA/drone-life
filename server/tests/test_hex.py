"""Pure axial hex math — the geometry every tile feature stands on."""

import math

from app.game import hex


def test_world_round_trip():
    for q in range(-15, 16):
        for r in range(-15, 16):
            n, e = hex.axial_to_world((q, r))
            assert hex.world_to_axial(n, e) == (q, r)


def test_points_near_center_round_to_that_cell():
    n, e = hex.axial_to_world((3, -2))
    inradius = hex.HEX_SIZE * hex.SQRT3 / 2
    for angle in range(0, 360, 30):
        dn = 0.9 * inradius * math.cos(math.radians(angle))
        de = 0.9 * inradius * math.sin(math.radians(angle))
        assert hex.world_to_axial(n + dn, e + de) == (3, -2)


def test_neighbors_are_one_pitch_away():
    center = hex.axial_to_world((2, 5))
    pitch = hex.SQRT3 * hex.HEX_SIZE
    cells = hex.neighbors((2, 5))
    assert len(cells) == len(set(cells)) == 6
    for cell in cells:
        n, e = hex.axial_to_world(cell)
        assert abs(math.hypot(n - center[0], e - center[1]) - pitch) < 1e-9


def test_ring_and_disc_counts():
    assert hex.ring((0, 0), 0) == [(0, 0)]
    assert len(hex.ring((4, -1), 1)) == 6
    assert len(hex.ring((4, -1), 2)) == 12
    assert len(hex.disc((4, -1), 2)) == 19
    assert set(hex.ring((4, -1), 1)) == set(hex.neighbors((4, -1)))
    assert set(hex.ring((4, -1), 2)) <= set(hex.disc((4, -1), 2))


def test_line_endpoints_and_adjacency():
    a, b = (-3, 1), (4, -5)
    cells = hex.line(a, b)
    assert cells[0] == a and cells[-1] == b
    assert len(cells) == hex.distance(a, b) + 1
    for prev, cur in zip(cells, cells[1:], strict=False):
        assert hex.distance(prev, cur) == 1


def test_cells_along_hugs_the_world_segment():
    cells = hex.cells_along((-40.0, -35.0), (40.0, -35.0))
    assert cells[0] == hex.world_to_axial(-40.0, -35.0)
    assert cells[-1] == hex.world_to_axial(40.0, -35.0)
    for cell in cells:
        _, e = hex.axial_to_world(cell)
        assert abs(e - (-35.0)) <= hex.HEX_SIZE + 1e-9, "stays within a cell of the segment"
    # edge-connected barrier: every consecutive pair shares an edge
    for prev, cur in zip(cells, cells[1:], strict=False):
        assert hex.distance(prev, cur) == 1


def test_rotate60_six_times_is_identity():
    cell = (3, -1)
    out = cell
    seen = set()
    for _ in range(6):
        out = hex.rotate60(out)
        seen.add(out)
    assert out == cell
    assert len(seen) == 6  # all six orientations distinct


def test_distance_symmetric():
    assert hex.distance((0, 0), (3, -1)) == hex.distance((3, -1), (0, 0)) == 3
    assert hex.distance((2, 2), (2, 2)) == 0


def test_pads_are_lattice_cells_inside_the_arena():
    from app.game.tiles import TileMap

    tm = TileMap()
    seen = set()
    for slot in range(20):
        cell = hex.pad_cell(slot)
        assert cell not in seen
        seen.add(cell)
        assert tm.in_bounds(cell)
        n, e = hex.pad_position(slot)
        assert hex.world_to_axial(n, e) == cell
        assert hex.axial_to_world(cell) == (n, e)
