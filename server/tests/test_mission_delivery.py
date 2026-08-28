"""Delivery mission rules through the WorldAPI seam — no MAVLink, no sim."""

import math
from dataclasses import replace
from itertools import pairwise

from app.game import hex
from app.game.building import HINT_EVERY, HINT_SUSTAIN, TOO_HIGH_SAY
from app.game.mission import MissionConfig
from app.game.missions.delivery import (
    CRATE_COUNT,
    CRATE_MAX,
    DROP_DWELL,
    EMPTY_HINT_SUSTAIN,
    EMPTY_SAY,
    FULL_SAY,
    LOST_SAY,
    MIN_SPAWN_DIST,
    PICKUP_DWELL,
    PILOTS_PER_CRATE,
    POINTS,
    SPAWN_STAGGER_S,
    DeliveryMission,
)
from tests.support.harness import FakeWorld, check_text, view


def make() -> tuple[DeliveryMission, FakeWorld]:
    world = FakeWorld()
    mission = DeliveryMission()
    world.start(mission)
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


def test_hud_counts_crates_and_deliveries():
    mission, world = make()
    assert mission.hud() == {"crates": 3, "delivered": 0}
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    world.views = [view(n=0.0, e=0.0, alt=1.5)]
    world.run(mission, DROP_DWELL + 0.3)
    assert mission.hud()["delivered"] == 1
    mission.reset(world)
    assert mission.hud()["delivered"] == 0


def test_delivery_posts_one_feed_row_carrying_the_points():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    world.views = [view(n=0.0, e=0.0, alt=1.5)]
    world.events.clear()
    world.run(mission, DROP_DWELL + 0.3)
    kinds = [ev["kind"] for ev in world.events if ev["kind"] in ("score", "delivery")]
    assert kinds == ["delivery"], "the named event replaces the generic '+10' row"
    assert f"+{POINTS}" in next(ev["msg"] for ev in world.events if ev["kind"] == "delivery")


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
    assert any(ev["kind"] == "crate_lost" for ev in world.events)


def test_reannounce_for_late_joiners():
    mission, world = make()
    world.texts.clear()
    world.run(mission, 25)  # past ANNOUNCE_EVERY
    assert sum("GAME: crate" in t for _, t in world.texts) >= 3


def test_reset_clears_and_respawns():
    mission, world = make()
    mission.reset(world)
    assert set(mission.crates) == {"1", "2", "3"}, "crate numbering restarts"
    assert mission.next_id == 4


# --------------------------------------------------- roster-scaled crate flow

def crowd(count: int) -> list:
    """Connected pilots parked well away from crates: on the pad row, too
    high to trigger any dwell."""
    return [view(f"d{i}", n=-90.0, e=float(3 * i), alt=10.0) for i in range(count)]


def test_crate_count_scales_with_pilots_staggered():
    # 7 crates for 21 pilots, 3 of them from setup: four staggered top-ups, so
    # the gap assertion below has something to be true about
    mission, world = make()
    world.views = crowd(7 * PILOTS_PER_CRATE)
    world.run(mission, 20 * SPAWN_STAGGER_S)
    assert len(mission.crates) == 7
    spawns = [ev["t"] for ev in world.events
              if ev["kind"] == "crate_spawn" and ev["t"] > 0]  # setup batch excluded
    assert len(spawns) == 4, "nothing staggered means nothing to check"
    gaps = [b - a for a, b in pairwise(spawns)]
    assert all(g >= SPAWN_STAGGER_S - 0.101 for g in gaps), gaps


def test_carried_crates_do_not_count_as_supply():
    """The starvation bug: the target counted every crate, carried ones
    included, so a full class flying the last crates home left nothing on the
    ground and nothing spawned to replace them."""
    mission, world = make()
    world.views = crowd(3 * PILOTS_PER_CRATE)  # target: 3 on the ground
    world.run(mission, 4 * SPAWN_STAGGER_S)
    assert len(mission.crates) == CRATE_COUNT

    # every crate goes up: one pilot per crate, hovering low over it
    grabbers = [view(f"g{i}", n=c.n, e=c.e, alt=1.5)
                for i, c in enumerate(mission.crates.values())]
    world.views = crowd(3 * PILOTS_PER_CRATE) + grabbers
    world.run(mission, PICKUP_DWELL + 0.3)
    assert all(mission.carry.item(g.id) for g in grabbers), "the supply is in the air"

    # ...and the ground refills under them, one staggered crate at a time
    world.run(mission, 8 * SPAWN_STAGGER_S)
    ground = mission._desired(world)  # the grabbers are pilots too
    assert mission._on_ground() == ground
    assert len(mission.crates) == ground + len(grabbers), "carried crates are still crates"


def test_crate_count_capped():
    mission, world = make()
    world.views = crowd(30)
    world.run(mission, 30 * SPAWN_STAGGER_S)
    assert len(mission.crates) == CRATE_MAX


def test_crate_count_drains_when_pilots_leave():
    mission, world = make()
    world.views = crowd(4 * PILOTS_PER_CRATE)
    world.run(mission, 10 * SPAWN_STAGGER_S)
    assert len(mission.crates) == 4
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]  # the room emptied
    world.run(mission, PICKUP_DWELL + 0.3)
    assert crate.carried_by == "d0"
    world.views = [replace(view(n=crate.n, e=crate.e), crashed=True, armed=False)]
    world.run(mission, 4 * SPAWN_STAGGER_S)
    assert len(mission.crates) == CRATE_COUNT, "no respawn above the shrunk target"


def test_spawn_keeps_min_dist_with_full_pad_row():
    mission = DeliveryMission()
    world = FakeWorld()
    world.config = MissionConfig(arena_half=100, alt_max=60,
                                 pads=[hex.pad_cell(i) for i in range(20)])
    world.start(mission)
    world.views = crowd(3 * CRATE_MAX)
    world.run(mission, (CRATE_MAX + 2) * SPAWN_STAGGER_S)
    assert len(mission.crates) == CRATE_MAX
    keep_away = [(0.0, 0.0), *world.config.pad_positions()]
    crates = list(mission.crates.values())
    for i, c in enumerate(crates):
        others = [(o.n, o.e) for o in crates[:i]] + keep_away
        assert all(math.hypot(c.n - n, c.e - e) >= MIN_SPAWN_DIST - 1e-9
                   for n, e in others), f"crate {c.id} spawned too close"


def test_spawn_under_pressure_picks_the_most_isolated_sample():
    # an arena so tight that no sample can honor MIN_SPAWN_DIST: the sampler
    # must fall back to the best draw seen, not whatever came 200th
    mission = DeliveryMission()
    world = FakeWorld()
    world.config = MissionConfig(arena_half=18, alt_max=60, pads=[hex.pad_cell(0)])
    world.start(mission)
    assert len(mission.crates) == CRATE_COUNT
    first = mission.crates["1"]
    # spawn box is ±3 around the dropoff; the best of 200 draws is far out in
    # the corner — a "last sample wins" fallback lands anywhere, often < 2 m
    assert math.hypot(first.n, first.e) >= 3.0


def test_worst_case_texts_fit_the_wire():
    # crate ids are unbounded within a session and the sim truncates at 50
    # chars silently — pin the formats at their widest
    check_text("GAME: crate 9999 at N -100 E -100")
    check_text("GAME: got crate 9999! drop at N 0 E 0")
    check_text("GAME: crate 9999 taken")
    check_text(f"GAME: delivered! +{POINTS} (team 100000)")


# ------------------------------------------------------------------- hints

def test_too_high_over_crate_hints_and_throttles():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=10.0)]  # hovering, too high
    world.run(mission, 25)
    nags = [t for target, t in world.texts if target == "d0" and t == TOO_HIGH_SAY]
    assert nags, "a sustained too-high hover must be told what to fix"
    assert 1 <= len(nags) <= 1 + 25 // HINT_EVERY, "nag paced, not per-tick"


def test_hands_full_over_a_crate_hints():
    mission, world = make()
    crates = list(mission.crates.values())
    first, second = crates[0], crates[1]
    world.views = [view(n=first.n, e=first.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    assert first.carried_by == "d0"
    world.views = [view(n=second.n, e=second.e, alt=1.5)]  # greedy: try another
    world.run(mission, HINT_SUSTAIN + 0.3)
    assert ("d0", FULL_SAY) in world.texts


def test_empty_handed_at_dropoff_hints():
    mission, world = make()
    world.views = [view(n=0.0, e=0.0, alt=1.5)]
    world.run(mission, EMPTY_HINT_SUSTAIN + 0.3)
    assert ("d0", EMPTY_SAY) in world.texts


def test_fresh_deliverer_is_not_nagged():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    world.views = [view(n=0.0, e=0.0, alt=1.5)]
    world.run(mission, DROP_DWELL + 0.3)
    assert world.score == POINTS
    world.run(mission, 2.0)  # linger a moment after delivering
    assert ("d0", EMPTY_SAY) not in world.texts


def test_carrier_crash_texts_the_loser():
    mission, world = make()
    crate = next(iter(mission.crates.values()))
    world.views = [view(n=crate.n, e=crate.e, alt=1.5)]
    world.run(mission, PICKUP_DWELL + 0.3)
    assert crate.carried_by == "d0"
    world.views = [replace(view(n=crate.n, e=crate.e), crashed=True, armed=False)]
    world.run(mission, 0.2)
    assert ("d0", LOST_SAY) in world.texts
