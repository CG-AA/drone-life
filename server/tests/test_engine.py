"""GameEngine: a mission bug must never kill the sim — and must be visible."""

from app.core.bus import EventBus
from app.game.engine import ERROR_EMIT_EVERY, GameEngine
from app.game.mission import Entity, Mission, MissionConfig
from app.sim.backend import DroneBackend, DroneView


class StubBackend(DroneBackend):
    async def spawn(self, drone_id: str, student_id: str, name: str, slot: int) -> DroneView:
        raise NotImplementedError

    async def remove(self, drone_id: str) -> None:
        raise NotImplementedError

    def drones(self):
        return []

    def send_text(self, drone_id: str, text: str, severity: int) -> None:
        pass


class BrokenMission(Mission):
    name = "broken"

    def setup(self, world):
        raise RuntimeError("setup boom")

    def tick(self, world, dt):
        raise KeyError("tick boom")

    def on_drone_event(self, world, drone, kind):
        raise ValueError("event boom")

    def entities(self):
        raise IndexError("entities boom")

    def reset(self, world):
        raise RuntimeError("reset boom")


def make_engine(mission: Mission) -> GameEngine:
    config = MissionConfig(arena_half=100.0, alt_max=60.0, pads=[])
    return GameEngine(StubBackend(), EventBus(), mission, config, seed=1)


def errors(engine: GameEngine) -> list[dict]:
    return [ev for ev in engine.bus.feed if ev["kind"] == "mission_error"]


def test_every_hook_is_guarded():
    engine = make_engine(BrokenMission())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [])
    assert engine.entities() == []
    engine.reset(0.2)
    # the sim survived all four raising hooks; reset still announced itself
    assert [ev["kind"] for ev in engine.bus.feed if ev["kind"] == "reset"] == ["reset"]


def test_mission_errors_reach_the_feed_throttled():
    engine = make_engine(BrokenMission())
    engine.start(0.0)
    for i in range(50):  # 5 s of 10 Hz failures
        engine.tick(i * 0.1, 0.1, [])
    assert len(errors(engine)) == 1  # throttled, not flooding the 200-deep ring
    engine.tick(ERROR_EMIT_EVERY + 1.0, 0.1, [])
    assert len(errors(engine)) == 2  # but a persistent bug re-surfaces


def test_healthy_mission_scores_through_the_api():
    class Scorer(Mission):
        name = "scorer"

        def tick(self, world, dt):
            world.add_score(10, "test")

        def entities(self):
            return [Entity(id="x", kind="crate", n=0.0, e=0.0, alt=0.0)]

    engine = make_engine(Scorer())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [])
    assert engine.score == 10
    assert [ev["kind"] for ev in engine.bus.feed] == ["score"]
    assert [ent.id for ent in engine.entities()] == ["x"]
