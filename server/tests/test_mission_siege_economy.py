"""Siege's economy through the WorldAPI seam: the team pool, wallets paid on
wave clear, the finite quarry, and the `say` command surface."""

from dataclasses import replace

from app.game import hex
from app.game.building import HINT_EVERY, HINT_SUSTAIN, PICKUP_DWELL
from app.game.missions.siege import (
    COINS_PER_KILL_EACH,
    QUARRY,
    QUARRY_EMPTY_SAY,
    QUARRY_STOCK_BASE,
    ZAP_DWELL,
    SiegeMission,
    _quarry_stock,
)
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, freeze_waves, hover, texts


def make(seated=()):
    world = FakeWorld()
    world.views = [view(d, n=-90.0, e=-76.0 + 6 * i) for i, d in enumerate(seated)]
    mission = SiegeMission()
    world.start(mission)
    return world, mission


def zap_one(world, m, drone_id="d0"):
    """One creep at the Keep's doorstep, one drone hovering low on it."""
    add_creep(m, (0, 2), uid=len(m.creeps) + 1)
    world.views = [hover((0, 2), alt=2.0, drone_id=drone_id)] + [
        v for v in world.views if v.id != drone_id]
    world.run(m, ZAP_DWELL + 0.2)
    assert not m.creeps, "the hover should have zapped it"


# ------------------------------------------------------------------- pool

def test_a_kill_pays_the_pool_per_seated_pilot():
    world, m = make(seated=("d0", "d1", "d2"))
    freeze_waves(m)
    zap_one(world, m)
    assert m.pool == COINS_PER_KILL_EACH * 3, "three seats: three coins per kill"
    zap_one(world, m)
    assert m.pool == COINS_PER_KILL_EACH * 6


def test_a_leak_pays_nothing():
    world, m = make(seated=("d0",))
    freeze_waves(m)
    add_creep(m, (0, 2), speed=2.0)
    world.run(m, 8.0)
    assert m.leaks == 1 and m.pool == 0


def test_wave_clear_splits_the_pool_and_carries_the_remainder():
    world, m = make(seated=("d0", "d1", "d2"))
    m.state, m.wave, m.pending, m.pool = "active", 2, 0, 25
    world.run(m, 0.3)
    assert m.state == "build"
    assert m.wallets == {"s-d0": 8, "s-d1": 8, "s-d2": 8}
    assert m.pool == 1, "25 // 3 each, 1 carries"
    paid = [(t, x) for t, x in world.texts if "coins, wallet" in x]
    assert paid == [("d0", "GAME: +8 coins, wallet 8"), ("d1", "GAME: +8 coins, wallet 8"),
                    ("d2", "GAME: +8 coins, wallet 8")]
    ev = next(ev for ev in world.events if ev["kind"] == "wave_clear")
    assert ev["msg"].endswith("+10, 8 coins each")
    assert ev["data"]["share"] == 8 and ev["data"]["pool"] == 1
    assert m.pilot("s-d1")["wallet"] == 8 and m.pilot("nobody")["wallet"] == 0
    assert m.hud()["pool"] == 1
    assert_grammar(world)


def test_an_empty_pool_pays_nobody_and_says_nothing_about_coins():
    world, m = make(seated=("d0", "d1"))
    m.state, m.wave, m.pending, m.pool = "active", 1, 0, 1
    world.run(m, 0.3)
    assert m.wallets == {} and m.pool == 1
    assert not any("coins" in x for _t, x in world.texts)
    ev = next(ev for ev in world.events if ev["kind"] == "wave_clear")
    assert "coins" not in ev["msg"] and ev["data"]["share"] == 0


def test_a_seat_between_runs_still_gets_its_share():
    world, m = make(seated=("d0", "d1"))
    world.views[1] = replace(world.views[1], connected=False, armed=False)
    m.state, m.wave, m.pending, m.pool = "active", 1, 0, 10
    world.run(m, 0.3)
    assert m.wallets == {"s-d0": 5, "s-d1": 5}, "seats, not live links"


def test_the_payout_line_fits_at_the_widest():
    world, m = make(seated=("d0",))
    m.wallets["s-d0"], m.pool = 9000, 999
    m.state, m.wave, m.pending = "active", 1, 0
    world.run(m, 0.3)  # FakeWorld checks every text against the 50-char law
    assert ("d0", "GAME: +999 coins, wallet 9999") in world.texts


# ----------------------------------------------------------------- quarry

def test_quarry_stock_follows_the_seats_and_the_wave():
    world, m = make()
    assert m.quarry.remaining == QUARRY_STOCK_BASE, "a fresh room: the grace stock"
    world, m = make(seated=("d0", "d1", "d2"))
    assert m.quarry.remaining == _quarry_stock(3, 0) == QUARRY_STOCK_BASE + 3
    m._start_wave(world, 2)
    assert m.quarry.remaining == _quarry_stock(3, 2)
    assert ("*", f"GAME: quarry restocked, {_quarry_stock(3, 2)} steel") in world.texts
    m.quarry.remaining = 1  # hoarded steel is not carried over: restock, not top-up
    m._start_wave(world, 3)
    assert m.quarry.remaining == _quarry_stock(3, 3)
    assert_grammar(world)


def test_pickups_spend_the_stock_and_an_empty_quarry_says_so():
    world, m = make(seated=("d0",))
    freeze_waves(m)
    m.quarry.remaining = 1
    world.views = [view("d0", n=QUARRY[0], e=QUARRY[1], alt=2.0)]
    world.run(m, PICKUP_DWELL + 0.2)
    assert m.carry.item("d0") == "steel" and m.quarry.remaining == 0
    m.carry.clear()  # empty-handed again, hovering the spent pile
    world.run(m, HINT_SUSTAIN + 0.2)
    assert texts(world).count(QUARRY_EMPTY_SAY) == 1
    world.run(m, 3.0)
    assert texts(world).count(QUARRY_EMPTY_SAY) == 1, "nagged, not spammed"
    world.run(m, HINT_EVERY)
    assert texts(world).count(QUARRY_EMPTY_SAY) == 2


def test_restock_line_fits_at_the_widest():
    world, m = make(seated=tuple(f"d{i}" for i in range(64)))
    m._start_wave(world, 99)  # 64 seats, a wave nobody will reach: still 50 chars
    assert any("quarry restocked" in t for t in texts(world))


# -------------------------------------------------------------------- say

def test_say_wallet_answers_with_the_balance():
    world, m = make(seated=("d0",))
    world.text(m, world.views[0], "wallet")
    assert world.texts[-1] == ("d0", "GAME: wallet 0 coins")
    m.wallets["s-d0"] = 12
    world.text(m, world.views[0], "  WALLET ")
    assert world.texts[-1] == ("d0", "GAME: wallet 12 coins")


def test_say_anything_else_gets_the_menu():
    world, m = make(seated=("d0",))
    world.text(m, world.views[0], "hello?")
    assert world.texts[-1] == ("d0", "GAME: say shop, wallet, quest or buy <item>")
    assert_grammar(world)


# ------------------------------------------------------------------ reset

def test_reset_zeroes_the_economy_and_restocks():
    world, m = make(seated=("d0", "d1"))
    m.pool, m.wallets["s-d0"], m.quarry.remaining = 7, 30, 0
    m.wave = 3  # so the reset counts as a round boundary
    m.reset(world)
    assert m.pool == 0 and m.wallets == {}
    assert m.quarry.remaining == _quarry_stock(2, 0)
    assert m.pilot("s-d0")["wallet"] == 0


def test_quarry_entity_carries_the_stock():
    world, m = make(seated=("d0",))
    q = next(e for e in m.entities(world) if e.kind == "tile_source")
    assert q.data == {"material": "steel", "remaining": _quarry_stock(1, 0)}
    assert (q.n, q.e) == QUARRY and hex.world_to_axial(q.n, q.e) == (14, -11)
