"""Terrain collision in the pure sim — no game code except one TileMap test.

Walls crash you from the side, roofs catch you from above, and the flat
default keeps yesterday's physics bit-for-bit.
"""

from app.game import hex
from app.game.tiles import TileMap
from app.sim import params as P
from app.sim.drone import Flight
from app.sim.world import World


class BoxTerrain:
    """Rectangular columns: (n0, n1, e0, e1, height). Game-free test stub."""

    def __init__(self, boxes):
        self.boxes = boxes

    def height_at(self, n: float, e: float) -> float:
        return max((h for n0, n1, e0, e1, h in self.boxes
                    if n0 <= n <= n1 and e0 <= e <= e1), default=0.0)


def spawn_at(world: World, n: float, e: float):
    drone = world.spawn("d0", "s0", "D0", slot=0)
    drone.n = n
    drone.e = e
    return drone


def run(world: World, seconds: float) -> list[str]:
    events = []
    for _ in range(int(round(seconds / P.DT))):
        events.extend(kind for _, kind in world.step(P.DT))
    return events


def fly(world: World, drone, alt: float) -> None:
    assert drone.set_mode(P.MODE_GUIDED, world.t)[0]
    assert drone.arm(world.t)[0]
    assert drone.takeoff(alt, world.t)[0]
    run(world, 8)
    assert drone.flight == Flight.FLY


def test_flat_default_flies_like_before():
    world = World()
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 5)
    drone.set_pos_target(10, 10, -5, None, world.t)
    run(world, 10)
    assert not drone.crashed
    drone.set_mode(P.MODE_LAND, world.t)
    events = run(world, 10)
    assert "landed" in events
    assert drone.alt == 0.0


def test_side_impact_crashes():
    world = World()
    world.terrain = BoxTerrain([(-10, 10, 18, 21, 4.0)])
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 2)
    drone.set_pos_target(0, 40, -2, None, world.t)
    events = run(world, 6)
    assert "crashed" in events
    assert drone.e < 18.01, "rewound outside the wall"
    assert any("CRASH: hit a wall" in text for _, text in drone.outbox)


def test_full_speed_never_tunnels_a_thin_wall():
    world = World()
    world.terrain = BoxTerrain([(-50, 50, 20.0, 20.3, 10.0)])
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 2)
    drone.set_pos_target(0, 60, -2, None, world.t)  # crosses the wall at ~10 m/s
    events = run(world, 8)
    assert "crashed" in events
    assert drone.e < 20.31


def test_descending_onto_a_roof_rides_it():
    world = World()
    world.terrain = BoxTerrain([(-5, 5, 15, 25, 4.0)])
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 10)
    drone.set_pos_target(0, 20, -10, None, world.t)
    run(world, 6)
    drone.set_pos_target(0, 20, -1, None, world.t)  # push down into the roof
    events = run(world, 6)
    assert "crashed" not in events
    assert abs(drone.alt - 4.0) < 1e-6, "held at roof height"


def test_land_on_stack_then_takeoff_from_it():
    world = World()
    world.terrain = BoxTerrain([(-5, 5, 15, 25, 4.0)])
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 10)
    drone.set_pos_target(0, 20, -10, None, world.t)
    run(world, 6)
    drone.set_mode(P.MODE_LAND, world.t)
    events = run(world, 10)
    assert "landed" in events
    assert drone.flight == Flight.IDLE
    assert abs(drone.alt - 4.0) < 1e-6, "touched down on the roof"
    # take off again from the rooftop: always climbs clear of the roof
    drone.set_mode(P.MODE_GUIDED, world.t)
    assert drone.arm(world.t)[0]
    assert drone.takeoff(1, world.t)[0]  # 1 m would be inside the stack: clamped
    run(world, 5)
    assert drone.flight == Flight.FLY
    assert drone.alt >= 4.4


def test_wreck_rests_on_roof_then_respawns():
    world = World()
    world.terrain = BoxTerrain([(-5, 5, 15, 25, 4.0)])
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 10)
    drone.set_pos_target(0, 20, -10, None, world.t)
    run(world, 6)
    drone.disarm(force=True, t=world.t)
    run(world, 2)  # falls 6 m at 8 m/s
    assert drone.crashed
    assert abs(drone.alt - 4.0) < 1e-6, "wreck rests on the rooftop"
    assert drone.on_ground
    events = run(world, P.CRASH_DOWN_TIME + 1)
    assert "respawned" in events
    assert (drone.n, drone.e) == (drone.spawn_n, drone.spawn_e)


def test_rtl_clears_max_legal_walls():
    world = World()
    # an 8 m wall (MAX_STACK * TILE_HEIGHT) across the whole route home
    world.terrain = BoxTerrain([(-60, -40, -100, 100, 8.0)])
    drone = spawn_at(world, 0.0, -76.0)  # spawn pad 0 is at (-90, -52)
    fly(world, drone, 2)
    drone.set_mode(P.MODE_RTL, world.t)
    events = run(world, 60)
    assert "crashed" not in events
    assert "landed" in events
    import math
    assert math.hypot(drone.n - drone.spawn_n, drone.e - drone.spawn_e) < 0.6
    assert drone.alt == 0.0


def test_tilemap_works_as_world_terrain():
    world = World()
    tm = TileMap()
    for cell in hex.line(hex.world_to_axial(-10, 20), hex.world_to_axial(10, 20)):
        tm.place(cell, "steel")
        tm.place(cell, "steel")
    world.terrain = tm
    drone = spawn_at(world, 0.0, 0.0)
    fly(world, drone, 2)
    drone.set_pos_target(0, 40, -2, None, world.t)
    events = run(world, 6)
    assert "crashed" in events
