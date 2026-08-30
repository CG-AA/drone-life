"""The sealed south gate: a triangle held over it opens a lane of raiders
whose bounty pays the room, and the formation breaking seals it."""

from app.game.missions.siege import (
    BONUS_GATE,
    BONUS_LANE_SIZE,
    FORM_HOLD_S,
    KINDS,
    RAIDER_POOL_EACH,
    SPAWN_GAP,
    ZAP_DWELL,
    SiegeMission,
)
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, freeze_waves


def make():
    world = FakeWorld()
    m = SiegeMission()
    world.start(m)
    freeze_waves(m)
    add_creep(m, (12, -6), uid=999, speed=0.0)  # holds the wave open
    m.state, m.wave = "active", 2
    return world, m


def formation(spread=8.0):
    n, e = BONUS_GATE
    return [view("d0", n=n, e=e, alt=6.0), view("d1", n=n + spread, e=e, alt=6.0),
            view("d2", n=n + spread / 2, e=e + spread * 0.866, alt=6.0)]


def test_a_held_triangle_opens_gate_s_and_raiders_pay_the_pool():
    world, m = make()
    world.views = formation()
    world.run(m, 0.2)
    told = [target for target, t in world.texts if t == "GAME: formation! hold 5 s to open gate S"]
    assert sorted(told) == ["d0", "d1", "d2"]
    assert not m.bonus_open
    world.run(m, FORM_HOLD_S)
    assert m.bonus_open and m.hud()["gate_s"] == "open"
    assert ("*", "GAME: south gate open! raiders pay the pool") in world.texts
    assert any(ev["kind"] == "gate_open" for ev in world.events)
    world.run(m, SPAWN_GAP * 2 + 0.2)
    raiders = [u for u in m.creeps.values() if u.kind == "raider"]
    assert len(raiders) >= 2 and all(u.gate == -1 for u in raiders)
    gate = next(e for e in m.entities(world) if e.id == "gate3")
    assert gate.data["label"] == "S" and gate.data["active"] and not gate.data["sealed"]
    # a zap on a raider: team points and the pot, no name on the board
    r = raiders[0]
    r.n, r.e, r.speed = 20.0, 20.0, 0.0  # park it under the zapper
    before, pool = world.score, m.pool
    world.views = [*formation(), view("d3", n=20.0, e=20.0, alt=2.0)]
    world.run(m, ZAP_DWELL * 2 + 0.3)  # 2 hp
    assert r.uid not in m.creeps
    assert world.score == before + KINDS["raider"].bounty
    assert world.scores[-1] == (KINDS["raider"].bounty, "D3 zapped a raider", None)
    assert m.pool == pool + 4 * (1 + RAIDER_POOL_EACH), "four seats: kill coin + raider coin"
    assert_grammar(world)


def test_breaking_the_formation_seals_the_gate_and_drops_the_lane():
    world, m = make()
    world.views = formation()
    world.run(m, FORM_HOLD_S + 0.3)
    assert m.bonus_open
    world.views = formation(20.0)  # too wide
    world.run(m, 0.2)
    assert not m.bonus_open and m.bonus_pending == 0
    assert ("*", "GAME: formation broken, gate S sealed") in world.texts
    assert any(ev["kind"] == "gate_sealed" for ev in world.events)
    world.views = formation()
    world.run(m, FORM_HOLD_S + 0.3)
    assert not m.bonus_open, "one opening per wave"
    m._start_wave(world, 3)
    add_creep(m, (12, -6), uid=998, speed=0.0)
    world.run(m, FORM_HOLD_S + 0.3)
    assert m.bonus_open, "a new wave, a new opening"


def test_the_gate_stays_sealed_between_waves_and_the_lane_is_bounded():
    world, m = make()
    m.state = "build"
    world.views = formation()
    world.run(m, FORM_HOLD_S + 1.0)
    assert not m.bonus_open and m.form_acc == 0.0
    m.state = "active"
    world.run(m, FORM_HOLD_S + 0.3 + SPAWN_GAP * (BONUS_LANE_SIZE + 2))
    raiders = [u for u in m.creeps.values() if u.kind == "raider"]
    assert len(raiders) == BONUS_LANE_SIZE and m.bonus_pending == 0
    assert m.bonus_open, "held: still open, just empty"


def test_gate_s_is_drawn_sealed_with_the_hold_progress():
    world, m = make()
    gate = next(e for e in m.entities(world) if e.id == "gate3")
    assert gate.data == {"label": "S", "active": False, "sealed": True, "hold": 0.0}
    assert (round(gate.n), round(gate.e)) == (-63, 5)
    world.views = formation()
    world.run(m, FORM_HOLD_S / 2)
    gate = next(e for e in m.entities(world) if e.id == "gate3")
    assert 0.4 <= gate.data["hold"] <= 0.6
