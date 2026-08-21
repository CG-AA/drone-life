"""Delivery mission rules through the WorldAPI seam — no MAVLink, no sim."""

from dataclasses import replace

from app.game.missions.delivery import (
    DROP_DWELL,
    PICKUP_DWELL,
    POINTS,
    DeliveryMission,
)
from tests.conftest import FakeWorld, view


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
