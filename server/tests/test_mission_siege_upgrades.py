"""The siege shop: wallets buy personal tiers (zap reach and dwell, speed,
tower range and rate) and cosmetics, by saying so."""

from app.game import hex
from app.game.missions.siege import (
    SHOP,
    TOWER_COOLDOWN,
    TOWER_COOLDOWN_MIN,
    TOWER_RANGE,
    TOWER_RANGE_PER_TIER,
    ZAP_DWELL,
    ZAP_DWELL_PER_TIER,
    ZAP_RADIUS,
    ZAP_RADIUS_PER_TIER,
    SiegeMission,
)
from tests.support.harness import FakeWorld, assert_grammar, view
from tests.test_mission_siege import add_creep, add_kind, build_tower, freeze_waves


def make(coins=100):
    world = FakeWorld()
    world.views = [view("d0", n=-90.0, e=-76.0)]
    m = SiegeMission()
    world.start(m)
    m.wallets["s-d0"] = coins
    return world, m


def say(world, m, text, drone_id="d0"):
    world.text(m, next(v for v in world.views if v.id == drone_id), text)
    return world.texts[-1][1]


# ------------------------------------------------------------------ buying

def test_the_shop_lists_its_prices_within_the_law():
    world, m = make()
    say(world, m, "shop")
    lines = [t for _d, t in world.texts if t.startswith("GAME: shop:") or "RRGGBB" in t]
    assert len(lines) == 3 and "zap 20/40/80" in lines[0] and "outline 10" in lines[1]
    assert_grammar(world)


def test_buying_climbs_the_tiers_and_debits_the_wallet():
    world, m = make(coins=100)
    assert say(world, m, "buy zap") == "GAME: bought zap I (80 left)"
    assert say(world, m, "buy zap") == "GAME: bought zap II (40 left)"
    assert say(world, m, "buy zap") == "GAME: need 80 coins, have 40"
    assert m.upgrades["s-d0"].zap == 2 and m.wallets["s-d0"] == 40
    m.wallets["s-d0"] = 500
    assert say(world, m, "buy zap") == "GAME: bought zap III (420 left)"
    assert say(world, m, "buy zap") == "GAME: zap maxed at III"
    bought = [ev for ev in world.events if ev["kind"] == "upgrade"]
    assert [ev["msg"] for ev in bought] == ["D0 bought zap I", "D0 bought zap II",
                                           "D0 bought zap III"]
    assert bought[0]["data"] == {"item": "zap", "level": 1, "price": 20}
    assert m.pilot("s-d0") == {"wallet": 420, "zap": 3, "speed": 0, "tower": 0,
                               "colour": None, "outline": None}


def test_unknown_items_and_menus():
    world, m = make()
    assert say(world, m, "buy jetpack") == "GAME: no such item, say shop"
    assert say(world, m, "buy") == "GAME: say shop, wallet or buy <item>"
    assert say(world, m, "dance") == "GAME: say shop, wallet or buy <item>"
    assert say(world, m, "BUY   Speed") == "GAME: bought speed I (70 left)"
    assert_grammar(world)


def test_cosmetics_take_a_hex_code_and_repeat():
    world, m = make(coins=25)
    assert say(world, m, "buy colour") == "GAME: bad colour, use #RRGGBB"
    assert say(world, m, "buy colour red") == "GAME: bad colour, use #RRGGBB"
    assert say(world, m, "buy colour #FF8800") == "GAME: bought colour #ff8800 (15 left)"
    assert say(world, m, "buy color #00ff00") == "GAME: bought colour #00ff00 (5 left)"
    assert say(world, m, "buy outline #123456") == "GAME: need 10 coins, have 5"
    assert m.pilot("s-d0")["colour"] == "#00ff00" and m.pilot("s-d0")["outline"] is None
    assert m.wallets["s-d0"] == 5


def test_the_widest_purchase_lines_fit():
    world, m = make(coins=9999 + SHOP["outline"][0])
    say(world, m, "buy outline #ffffff")  # "GAME: bought outline #ffffff (9999 left)"
    assert world.texts[-1][1].endswith("(9999 left)")
    m.wallets["s-d0"] = 9999 + SHOP["speed"][0]
    assert say(world, m, "buy speed") == "GAME: bought speed I (9999 left)"
    m.wallets["s-d0"] = 9999 + SHOP["speed"][1]
    assert say(world, m, "buy speed") == "GAME: bought speed II (9999 left)"
    assert_grammar(world)


# ----------------------------------------------------------------- effects

def test_zap_tier_reaches_further_and_lands_sooner():
    world, m = make(coins=100)
    freeze_waves(m)
    cn, ce = hex.axial_to_world((0, 2))
    add_creep(m, (0, 2))
    just_out = ZAP_RADIUS + ZAP_RADIUS_PER_TIER * 0.5  # 4.5 m: tier 0 misses, tier I reaches
    world.views = [view("d0", n=cn + just_out, e=ce, alt=2.0)]
    world.run(m, ZAP_DWELL + 0.3)
    assert m.creeps, "stock reach is 4 m"
    say(world, m, "buy zap")
    world.run(m, ZAP_DWELL - ZAP_DWELL_PER_TIER + 0.2)
    assert not m.creeps, "tier I: 5 m reach, 1.25 s dwell"


def test_zap_tier_rearms_faster_on_a_multi_hp_creep():
    world, m = make(coins=100)
    freeze_waves(m)
    brute = add_kind(m, (0, 2), "brute")
    say(world, m, "buy zap")
    say(world, m, "buy zap")  # tier II: dwell 1.0 s
    cn, ce = hex.axial_to_world((0, 2))
    world.views = [view("d0", n=cn, e=ce, alt=2.0)]
    world.run(m, 3 * (ZAP_DWELL - 2 * ZAP_DWELL_PER_TIER) + 0.3)
    assert brute.hp <= 0 or not m.creeps, "three 1.0 s dwells in ~3.3 s"


def test_speed_tier_scales_the_drone_and_survives_a_reconnect():
    world, m = make(coins=100)
    assert world.speeds == {}
    say(world, m, "buy speed")
    assert world.speeds == {"d0": 1.25}
    world.drone_event(m, world.views[0], "connected")  # respawn / rejoin: re-applied
    assert world.speeds["d0"] == 1.25
    world.drone_event(m, view("d1", n=-90.0, e=-70.0), "connected")
    assert world.speeds["d1"] == 1.0, "a pilot who bought nothing flies stock"
    m.wave = 2
    m.reset(world)
    assert world.speeds["d0"] == 1.0 and m.upgrades == {}


def test_tower_tier_extends_reach_and_floors_the_cooldown():
    world, m = make(coins=200)
    freeze_waves(m)
    build_tower(world, m, (4, 1))
    tn, te = hex.axial_to_world((4, 1))
    world.views = [view("d0", n=-90.0, e=-76.0)]
    far = add_creep(m, (4, 1), uid=7)
    far.n, far.e = tn + TOWER_RANGE + TOWER_RANGE_PER_TIER * 0.5, te  # 18 m out
    world.run(m, TOWER_COOLDOWN + 0.3)
    assert m.creeps, "stock range is 16 m"
    say(world, m, "buy tower")
    world.run(m, 0.3)
    assert not m.creeps, "tier I reaches 20 m"
    tower = next(e for e in m.entities(world) if e.kind == "tower")
    assert tower.data == {"range": TOWER_RANGE + TOWER_RANGE_PER_TIER, "tier": 1}
    say(world, m, "buy tower")  # tier II: cooldown 2.0 - 1.0 = 1.0, at the floor
    assert m._tower_stats(m.towers[(4, 1)])[1] == TOWER_COOLDOWN_MIN
    assert say(world, m, "buy tower") == "GAME: tower maxed at II"
