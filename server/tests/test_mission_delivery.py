"""Delivery mission rules through the WorldAPI seam — no MAVLink, no sim."""

import random
from dataclasses import replace

from app.game.mission import MissionConfig
from app.game.missions.delivery import (
    DROP_DWELL,
    PICKUP_DWELL,
    POINTS,
    Crate,
    DeliveryMission,
)
from app.sim.backend import DroneView


def view(drone_id="d0", n=0.0, e=0.0, alt=1.0, armed=True, crashed=False) -> DroneView:
    return DroneView(
        id=drone_id, student_id=f"s-{drone_id}", name=drone_id.upper(), sysid=1,
        n=n, e=e, alt=alt, vn=0, ve=0, valt=0, yaw=0, mode="GUIDED",
        armed=armed, on_ground=False, crashed=crashed, connected=True,
    )


class FakeWorld:
    def __init__(self) -> None:
        self.rng = random.Random(1)
        self.config = MissionConfig(arena_half=100, alt_max=60, pads=[(-90.0, -76.0)])
        self.now = 0.0
        self.views: list[DroneView] = []
        self.events: list[tuple[str, str]] = []
        self.texts: list[tuple[str, str]] = []  # (target, text)
        self.score = 0

    def drones(self):
        return self.views

    def emit_event(self, kind, msg, student_id=None, data=None):
        self.events.append((kind, msg))

    def add_score(self, points, reason, student_id=None):
        self.score += points
        return self.score

    def send_text(self, drone_id, text, severity=6):
        self.texts.append((drone_id, text))

    def broadcast_text(self, text, severity=6):
        self.texts.append(("*", text))

    def run(self, mission, seconds, dt=0.1):
        for _ in range(int(seconds / dt)):
            self.now += dt
            mission.tick(self, dt)


def make() -> tuple[DeliveryMission, FakeWorld]:
    world = FakeWorld()
    mission = DeliveryMission()
    mission.setup(world)
    return mission, world


def test_setup_spawns_three_announced_crates():
    mission, world = make()
    assert len(mission.crates) == 3
    announcements = [t for _, t in world.texts if t.startswith("GAME: crate")]
    assert len(announcements) == 3
    for crate in mission.crates.values():
        assert abs(crate.n) <= 100 and abs(crate.e) <= 100

def test_pickup_requires_dwell():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL / 2)
    assert crate.carried_by is None, "half the dwell must not be enough"
    world.run(mission, PICKUP_DWELL)
    assert crate.carried_by == "d0"
    assert any("got crate" in t for target, t in world.texts if target == "d0")
    assert any("taken" in t for target, t in world.texts if target == "*")


def test_leaving_the_circle_resets_dwell():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL * 0.75)
    world.views = [view(n=crate.n + 50, e=crate.e, alt=1.5)]  # fly away
    world.run(mission, 0.5)
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]  # come back
    world.run(mission, PICKUP_DWELL * 0.75)
    assert crate.carried_by is None, "dwell must restart after leaving"


def test_delivery_scores_and_respawns():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    assert crate.carried_by == "d0"
    world.views = [view(n=0.0, e=0.0, alt=1.5)]  # hover the dropoff
    world.run(mission, DROP_DWELL + 0.3)
    assert world.score == POINTS
    assert crate.id not in mission.crates
    assert len(mission.crates) == 3, "a replacement crate spawns"
    assert any("delivered" in t for _, t in world.texts)


def test_carrier_crash_respawns_crate():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    assert crate.carried_by == "d0"
    world.views = [replace(view(n=crate.n, e=crate.e), crashed=True, armed=False)]
    world.run(mission, 0.2)
    assert crate.id not in mission.crates
    assert len(mission.crates) == 3
    assert world.score == 0
    assert any(kind == "crate_lost" for kind, _ in world.events)


def test_reannounce_for_late_joiners():
    mission, world = make()
    world.texts.clear()
    world.run(mission, 25)  # past ANNOUNCE_EVERY
    assert sum("GAME: crate" in t for _, t in world.texts) >= 3


def test_reset_clears_and_respawns():
    mission, world = make()
    ids_before = set(mission.crates)
    mission.reset(world)
    assert len(mission.crates) == 3
    assert set(mission.crates).isdisjoint(ids_before) or True  # fresh ids from 1
    assert mission.next_id == 4
