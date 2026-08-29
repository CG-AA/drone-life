"""Ground-unit walker: move, climb, chew, pedestal — over hand-built maps."""

import math

from app.game import hex, path
from app.game.tiles import TILE_HEIGHT, TileMap
from app.game.units import GroundUnit, step_units

GOAL = (0, 0)
DT = 0.1


def unit_at(cell, speed=1.0, uid=0):
    n, e = hex.axial_to_world(cell)
    return GroundUnit(uid=uid, n=n, e=e, speed=speed)


def run(us, tm, flow, seconds, chew_s=1.0):
    """Step for `seconds`; collect (time, result) of eventful ticks."""
    events = []
    t = 0.0
    for _ in range(round(seconds / DT)):
        result = step_units(us, tm, flow, DT, chew_s)
        t += DT
        if result.arrived or result.chews:
            events.append((t, result))
    return events


def test_chew_rate_scales_the_clock():
    tm = TileMap()
    for wall in hex.ring(GOAL, 1):  # a 2-high ring: the only way in is through
        tm.place(wall, "steel")
        tm.place(wall, "steel")
    flow = path.flood(tm, GOAL, climb=1)
    slow, fast = unit_at((0, 2), uid=1), unit_at((0, 2), uid=2)
    fast.chew_rate = 2.0
    us = [slow, fast]
    chewed_at = {}
    t = 0.0
    for _ in range(round(20 / DT)):
        result = step_units(us, tm, flow, DT, chew_s=4.0)
        t += DT
        for u, _cell in result.chews:
            chewed_at.setdefault(u.uid, round(t, 1))
        if len(chewed_at) == 2:
            break
    assert chewed_at[2] < chewed_at[1], chewed_at
    assert abs(chewed_at[2] * 2 - chewed_at[1]) < 0.3, "2x chew rate: half the time"


def test_walks_to_goal_and_arrives_on_schedule():
    tm = TileMap()
    flow = path.flood(tm, GOAL, climb=1)
    u = unit_at((0, 1), speed=1.0)  # one 5.196 m pitch out; boundary at half
    assert run([u], tm, flow, 2.0) == [], "still in its own cell"
    events = run([u], tm, flow, 1.2)
    assert events and events[0][1].arrived == [u], "crossed into the goal cell"
    expected = math.degrees(math.atan2(-hex.SQRT3 / 2, -1.5))  # toward origin
    assert abs(u.heading - expected) < 1.0


def test_speed_zero_never_moves():
    tm = TileMap()
    flow = path.flood(tm, GOAL, climb=1)
    u = unit_at((0, 3), speed=0.0)
    start = (u.n, u.e)
    assert run([u], tm, flow, 3.0) == []
    assert (u.n, u.e) == start


def test_climbs_a_step_and_rides_the_stack_top():
    tm = TileMap()
    tm.place((0, 1), "steel")  # 1-high, climbable on the straight path
    flow = path.flood(tm, GOAL, climb=1)
    u = unit_at((0, 2), speed=2.0)
    tops = set()
    for _ in range(80):
        step_units([u], tm, flow, DT, chew_s=1.0)
        tops.add(u.alt)
        if u.cell == GOAL:
            break
    assert u.cell == GOAL
    assert tops == {0.0, TILE_HEIGHT}, "alt tracked ground and the tile top"


def test_two_stack_blocks_and_chew_fires_at_chew_s():
    tm = TileMap()
    wall = (0, 1)
    tm.place(wall, "steel")
    tm.place(wall, "steel")
    # a lone wall cell would be routed around: zero the chew cost so the
    # field points straight through it and the walker must confront it
    flow = path.flood(tm, GOAL, climb=1, chew_cost=0.0)
    assert flow.toward((0, 2)) == wall
    u = unit_at((0, 2), speed=1.0)
    events = run([u], tm, flow, 2.05, chew_s=2.0)
    assert len(events) == 1
    t, result = events[0]
    assert abs(t - 2.0) < DT / 2, "chew completes at exactly chew_s"
    assert result.chews == [(u, wall)]
    assert u.cell == (0, 2), "chewing units stand still"


def test_pedestal_rule_chews_own_cell():
    tm = TileMap()
    perch = (0, 3)
    tm.place(perch, "steel")
    tm.place(perch, "steel")
    flow = path.flood(tm, GOAL, climb=1)
    u = unit_at(perch)
    u.alt = tm.top_alt(perch)
    events = run([u], tm, flow, 1.05, chew_s=1.0)
    assert events and events[0][1].chews == [(u, perch)], "digs itself down"


def test_chew_then_remove_then_walk_through():
    tm = TileMap()
    wall = (0, 1)
    tm.place(wall, "steel")
    tm.place(wall, "steel")
    flow = path.flood(tm, GOAL, climb=1, chew_cost=0.0)  # head straight at it
    u = unit_at((0, 2), speed=2.0)
    events = run([u], tm, flow, 1.05, chew_s=1.0)
    assert events[0][1].chews == [(u, wall)]
    tm.remove_top(wall)  # the caller's job, on the chew event
    flow = path.flood(tm, GOAL, climb=1)  # ...and re-flood on version change
    assert u.chewing
    events = run([u], tm, flow, 6.0, chew_s=1.0)
    assert not u.chewing, "walking clears the chew state"
    assert events and events[-1][1].arrived == [u], "1-high remnant is a ramp"


def test_chew_factor_scales_the_clock_by_material():
    tm = TileMap()
    for wall in hex.ring(GOAL, 1):
        tm.place(wall, "steel")
        tm.place(wall, "steel")
    for wall in hex.ring(GOAL, 2):  # an outer 3-high clay ring: two chews to climb it
        tm.place(wall, "clay")
        tm.place(wall, "clay")
        tm.place(wall, "clay")
    flow = path.flood(tm, GOAL, climb=1)
    u = unit_at((0, 3), uid=1)
    chewed = []
    t = 0.0
    while t < 20 and len(chewed) < 3:
        r = step_units([u], tm, flow, DT, 6.0, chew_factor={"clay": 3.0})
        t += DT
        for _unit, cell in r.chews:
            chewed.append((round(t, 1), tm.top(cell)))
            tm.remove_top(cell)
            flow = path.flood(tm, GOAL, climb=1)
    assert [m for _t, m in chewed[:2]] == ["clay", "clay"], "the outer ring goes first"
    clay_each = chewed[1][0] - chewed[0][0]
    assert abs(clay_each - 2.0) < 0.3, "6 s / 3x = 2 s per clay tile"
    assert chewed[2][1] == "steel" and chewed[2][0] - chewed[1][0] > 5.0, "steel at 1x"
