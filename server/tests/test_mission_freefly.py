"""Freefly: the warmup mission says hello, so drone.events() is never empty."""

from app.game.missions.freefly import WELCOME, FreeFlyMission
from tests.support.harness import FakeWorld, view


def test_welcome_reaches_the_drone_that_connected():
    world = FakeWorld()
    mission = FreeFlyMission()
    world.start(mission)
    world.drone_event(mission, view("d0"), "connected")
    world.drone_event(mission, view("d1"), "armed")  # not a connect: silent
    assert [t for target, t in world.texts if target == "d0"] == list(WELCOME)
    assert not [t for target, t in world.texts if target == "d1"]


def test_freefly_never_scores():
    world = FakeWorld()
    mission = FreeFlyMission()
    world.start(mission)
    world.views = [view("d0", n=50, e=50, alt=1)]
    world.run(mission, 30)
    assert world.scores == [] and world.events == []
