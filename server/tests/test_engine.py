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

    def set_speed(self, drone_id: str, scale: float) -> None:
        self.speeds = getattr(self, "speeds", {})
        self.speeds[drone_id] = scale


class BrokenMission(Mission):
    name = "broken"

    def setup(self, world):
        raise RuntimeError("setup boom")

    def tick(self, world, dt):
        raise KeyError("tick boom")

    def on_drone_event(self, world, drone, kind):
        raise ValueError("event boom")

    def on_text(self, world, drone, text):
        raise ValueError("text boom")

    def pilot(self, student_id):
        raise LookupError("pilot boom")

    def entities(self, world):
        raise IndexError("entities boom")

    def reset(self, world):
        raise RuntimeError("reset boom")


def make_engine(mission: Mission) -> GameEngine:
    config = MissionConfig(arena_half=100.0, alt_max=60.0, pads=[])
    return GameEngine(StubBackend(), EventBus(), mission, config, seed=1)


def errors(engine: GameEngine) -> list[dict]:
    return [ev for ev in engine.bus.feed if ev["kind"] == "mission_error"]


def a_view(drone_id="d0") -> DroneView:
    return DroneView(id=drone_id, student_id=f"s-{drone_id}", name=drone_id, sysid=1,
                     n=0, e=0, alt=0, vn=0, ve=0, valt=0, yaw=0, mode="GUIDED",
                     armed=False, on_ground=True, crashed=False, connected=True)


def test_every_hook_is_guarded():
    engine = make_engine(BrokenMission())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [(a_view(), "connected")], [(a_view(), "wallet")])
    assert engine.entities() == []
    assert engine.pilot("s-d0") == {}
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


def test_texts_arrive_after_events_and_before_tick():
    seen = []

    class Listener(Mission):
        name = "listener"

        def on_drone_event(self, world, drone, kind):
            seen.append(("event", drone.id, kind))

        def on_text(self, world, drone, text):
            seen.append(("text", drone.id, text))

        def tick(self, world, dt):
            seen.append(("tick",))

    engine = make_engine(Listener())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [(a_view("d1"), "armed")],
                [(a_view("d1"), "wallet"), (a_view("d2"), "buy zap")])
    assert seen == [("event", "d1", "armed"), ("text", "d1", "wallet"),
                    ("text", "d2", "buy zap"), ("tick",)]
    engine.tick(0.2, 0.1, [])  # texts default to none
    assert seen[-1] == ("tick",) and len(seen) == 5


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


def test_set_speed_reaches_the_backend():
    class Buyer(Mission):
        name = "buyer"

        def tick(self, world, dt):
            world.set_speed("d7", 1.25)

    engine = make_engine(Buyer())
    engine.start(0.0)
    engine.tick(0.1, 0.1, [])
    assert engine.backend.speeds == {"d7": 1.25}


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


def test_per_pilot_tally_follows_the_team_score_and_clears_on_reset():
    engine = make_engine(QuietMission())
    engine.api.add_score(10, "crate", student_id="s1")
    engine.api.add_score(10, "crate", student_id="s2")
    engine.api.add_score(15, "tower", student_id="s1", feed=False)
    engine.api.add_score(-25, "keep fell")  # a team loss belongs to nobody
    assert engine.scores == {"s1": 25, "s2": 10}
    assert engine.score == 10
    engine.reset(now=1.0)
    assert engine.scores == {} and engine.score == 0
