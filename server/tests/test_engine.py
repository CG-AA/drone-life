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

    def entities(self, world):
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

        def entities(self, world):
            return [Entity(id="x", kind="crate", n=0.0, e=0.0, alt=0.0)]

    engine = make_engine(Scorer())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [])
    assert engine.score == 10
    assert [ev["kind"] for ev in engine.bus.feed] == ["score"]
    assert [ent.id for ent in engine.entities()] == ["x"]


def test_reset_lets_the_mission_read_the_final_score_first():
    seen = []

    class Summariser(Mission):
        name = "summariser"

        def reset(self, world):
            seen.append(world.score)

    engine = make_engine(Summariser())
    engine.start(0.0)
    engine.api.add_score(42, "x")
    engine.reset(1.0)
    assert seen == [42] and engine.score == 0


def test_quiet_score_counts_and_celebrates_without_a_feed_row():
    class Silent(Mission):
        name = "silent"

        def tick(self, world, dt):
            world.add_score(60, "tower kill", student_id="s1", feed=False)

    engine = make_engine(Silent())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [])
    engine.tick(0.2, 0.1, [])
    assert engine.score == 120
    kinds = [ev["kind"] for ev in engine.bus.feed]
    assert "score" not in kinds, "quiet scoring posts no '+N' rows"
    assert kinds.count("milestone") == 1, "…but the century crossing still celebrates"


class QuietMission(Mission):
    name = "quiet"


def milestones(engine: GameEngine) -> list[dict]:
    return [ev for ev in engine.bus.feed if ev["kind"] == "milestone"]


def test_milestone_fires_on_upward_century_cross():
    engine = make_engine(QuietMission())
    for _ in range(9):
        engine.api.add_score(10, "crate delivered")
    assert milestones(engine) == []
    engine.api.add_score(10, "crate delivered")
    assert [ev["msg"] for ev in milestones(engine)] == ["team passes 100 points!"]
    engine.api.add_score(150, "big finish")  # one crossing event even for a jump
    assert [ev["msg"] for ev in milestones(engine)][-1] == "team passes 200 points!"
    assert len(milestones(engine)) == 2


def test_milestone_never_fires_on_a_loss():
    engine = make_engine(QuietMission())
    engine.api.add_score(105, "head start")
    assert len(milestones(engine)) == 1
    engine.api.add_score(-25, "keep fell")  # dips below 100
    assert len(milestones(engine)) == 1, "losses never celebrate"


def test_climbing_out_of_the_red_is_not_a_milestone():
    """Siege can drive the team negative (the keep is -25 each fall). Floor
    division put the first point back in the black at "team passes 0 points!" —
    a celebration for being broke."""
    engine = make_engine(QuietMission())
    engine.api.add_score(-25, "keep fell")
    engine.api.add_score(2, "creep down")  # -23: still red, still crossing 0//100
    assert milestones(engine) == []
    engine.api.add_score(30, "wave clear")  # +7: black, but nowhere near 100
    assert milestones(engine) == []
    engine.api.add_score(95, "long haul")  # 102: the real first century
    assert [ev["msg"] for ev in milestones(engine)] == ["team passes 100 points!"]


def test_deep_in_the_red_a_gain_that_stays_red_never_celebrates():
    engine = make_engine(QuietMission())
    engine.api.add_score(-150, "a bad round")
    engine.api.add_score(100, "recovery")  # -50: crosses -100//100, still a loss
    assert milestones(engine) == []


def test_milestone_recelebrates_a_recrossed_mark():
    engine = make_engine(QuietMission())
    engine.api.add_score(105, "head start")
    engine.api.add_score(-25, "keep fell")
    engine.api.add_score(30, "wave clear")  # back over 100
    assert len(milestones(engine)) == 2, "a re-earned mark is worth re-celebrating"
