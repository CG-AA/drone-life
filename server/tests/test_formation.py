"""triangle(): three airborne drones in a real triangle over a point."""

from app.game.formation import triangle
from tests.support.harness import view


def trio(spread=8.0, **over):
    return [view("d0", n=0.0, e=0.0, alt=6.0, **over), view("d1", n=spread, e=0.0, alt=6.0, **over),
            view("d2", n=spread / 2, e=spread * 0.866, alt=6.0, **over)]


def test_an_equilateral_eight_metre_triangle_passes():
    got = triangle(trio(8.0), 3.0, 2.0, 15.0, 6.0, 12.0)
    assert got is not None and [d.id for d in got] == ["d0", "d1", "d2"]


def test_too_tight_too_wide_and_too_few_fail():
    assert triangle(trio(4.0), 3.0, 2.0, 15.0, 6.0, 12.0) is None
    assert triangle(trio(14.0), 3.0, 2.0, 15.0, 6.0, 12.0) is None
    assert triangle(trio(8.0)[:2], 3.0, 2.0, 15.0, 6.0, 12.0) is None


def test_a_line_is_not_a_triangle():
    line = [view("d0", n=0.0, e=0.0, alt=6.0), view("d1", n=6.0, e=0.0, alt=6.0),
            view("d2", n=12.0, e=0.0, alt=6.0)]
    assert triangle(line, 6.0, 0.0, 15.0, 6.0, 12.0) is None
    bent = [*line[:2], view("d2", n=6.0, e=7.0, alt=6.0)]
    assert triangle(bent, 6.0, 0.0, 15.0, 6.0, 12.0) is not None


def test_only_airborne_armed_drones_near_the_point_count():
    far = trio(8.0)
    assert triangle(far, 100.0, 100.0, 15.0, 6.0, 12.0) is None
    assert triangle(trio(8.0, armed=False), 3.0, 2.0, 15.0, 6.0, 12.0) is None
    assert triangle(trio(8.0, crashed=True), 3.0, 2.0, 15.0, 6.0, 12.0) is None


def test_four_drones_with_one_valid_triple_and_determinism():
    drones = [*trio(8.0), view("d3", n=40.0, e=40.0, alt=6.0)]
    a = triangle(drones, 3.0, 2.0, 60.0, 6.0, 12.0)
    b = triangle(list(reversed(drones)), 3.0, 2.0, 60.0, 6.0, 12.0)
    assert a is not None and [d.id for d in a] == [d.id for d in b] == ["d0", "d1", "d2"]
