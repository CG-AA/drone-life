"""Building primitives: dwell, carry, placement — the reusable mechanics."""

from dataclasses import replace

from app.game import hex
from app.game.building import (
    PLACE_CLEAR,
    PLACE_DWELL,
    PLACE_WINDOW,
    CarrySlots,
    DwellTracker,
    PlaceTracker,
    TileSource,
    crush_ok,
    fmt_cell,
    hover_alt_hint,
    place_window,
    tick_sources,
)
from app.game.tiles import TILE_HEIGHT, TileMap
from tests.conftest import view


def run_dwell(tracker, drones, n, e, seconds, dt=0.1, eligible=None):
    for _ in range(int(seconds / dt)):
        winner = tracker.update(drones, n, e, dt, eligible)
        if winner is not None:
            return winner
    return None


# ------------------------------------------------------------- DwellTracker

def test_dwell_accumulates_and_completes():
    tracker = DwellTracker(radius=2.0, max_alt=3.0, dwell_s=1.0)
    d = view(n=0.0, e=0.0, alt=1.0)
    assert run_dwell(tracker, [d], 0, 0, 0.5) is None
    assert run_dwell(tracker, [d], 0, 0, 0.6) is d
    assert tracker.acc == {}, "winning clears the accumulators"


def test_dwell_resets_on_exit():
    tracker = DwellTracker(radius=2.0, max_alt=3.0, dwell_s=1.0)
    near, far = view(n=0.0, e=0.0), view(n=50.0, e=0.0)
    run_dwell(tracker, [near], 0, 0, 0.8)
    run_dwell(tracker, [far], 0, 0, 0.2)  # left the circle
    assert run_dwell(tracker, [near], 0, 0, 0.8) is None, "timer restarted"


def test_dwell_gates():
    tracker = DwellTracker(radius=2.0, max_alt=3.0, dwell_s=0.5)
    high = view(alt=10.0)
    assert run_dwell(tracker, [high], 0, 0, 2.0) is None
    crashed = replace(view(), crashed=True, armed=False)
    assert run_dwell(tracker, [crashed], 0, 0, 2.0) is None
    blocked = view()
    assert run_dwell(tracker, [blocked], 0, 0, 2.0, eligible=lambda d: False) is None


# --------------------------------------------------------------- CarrySlots

def test_carry_one_item_per_drone():
    carry = CarrySlots()
    assert carry.give("d0", "steel") is True
    assert carry.give("d0", "clay") is False, "hands full"
    assert carry.item("d0") == "steel"
    assert carry.take("d0") == "steel"
    assert carry.take("d0") is None


def test_sync_losses_on_crash_and_vanish():
    carry = CarrySlots()
    carry.give("d0", "steel")
    carry.give("d1", "clay")
    crashed = replace(view("d0"), crashed=True, armed=False)
    lost = carry.sync_losses([crashed])  # d1 has vanished entirely
    assert sorted(lost) == [("d0", "steel"), ("d1", "clay")]
    assert carry.item("d0") is None and carry.item("d1") is None


def test_carried_entities_follow_the_drone():
    carry = CarrySlots()
    carry.give("d0", "clay")
    ents = carry.entities([view("d0", n=5.0, e=6.0, alt=7.0), view("d1")])
    assert len(ents) == 1
    ent = ents[0]
    assert (ent.kind, ent.n, ent.e, ent.alt) == ("tile_carried", 5.0, 6.0, 7.0)
    assert ent.data == {"carried_by": "d0", "material": "clay"}


# ------------------------------------------------------ placement geometry

def test_place_window_and_hint_track_stack_height():
    tm = TileMap()
    cell = (0, 0)
    for height in range(4):
        new_top = (height + 1) * TILE_HEIGHT
        assert place_window(tm, cell) == (new_top + PLACE_CLEAR, new_top + PLACE_WINDOW)
        assert hover_alt_hint(tm, cell) == 2 * height + 4
        tm.place(cell, "steel")


def test_fmt_cell_rounds_the_center():
    cell = hex.world_to_axial(10.0, -55.0)
    n, e = hex.axial_to_world(cell)
    assert fmt_cell(cell) == f"N {round(n)} E {round(e)}"


def test_crush_rule():
    tm = TileMap()
    cell = (2, 2)
    n, e = hex.axial_to_world(cell)
    placer = view("d0", n=n, e=e, alt=3.0)
    low_bystander = view("d1", n=n, e=e, alt=1.0)
    high_bystander = view("d1", n=n, e=e, alt=10.0)
    assert crush_ok(tm, cell, [placer], "d0") is True, "the placer never blocks itself"
    assert crush_ok(tm, cell, [placer, low_bystander], "d0") is False
    assert crush_ok(tm, cell, [placer, high_bystander], "d0") is True


# ------------------------------------------------------------- PlaceTracker

def hover(cell, alt, drone_id="d0"):
    n, e = hex.axial_to_world(cell)
    return view(drone_id, n=n, e=e, alt=alt)


def run_place(tracker, drones, seconds, dt=0.1):
    all_placed, all_refused = [], []
    for _ in range(int(round(seconds / dt))):
        placed, refused = tracker.tick(drones, dt)
        all_placed.extend(placed)
        all_refused.extend(refused)
    return all_placed, all_refused


def test_place_commits_after_dwell():
    tm = TileMap()
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry)
    cell = (3, 3)
    d = hover(cell, alt=4.0)  # empty cell window is (2.4, 5.0]
    placed, refused = run_place(tracker, [d], PLACE_DWELL / 2)
    assert placed == [] and refused == []
    placed, _ = run_place(tracker, [d], PLACE_DWELL)
    assert len(placed) == 1
    assert placed[0].cell == cell and placed[0].material == "steel"
    assert tm.stack(cell) == ("steel",)
    assert carry.item("d0") is None, "the tile left the drone's hands"


def test_place_window_exit_resets():
    tm = TileMap()
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry)
    cell = (3, 3)
    run_place(tracker, [hover(cell, alt=4.0)], PLACE_DWELL * 0.7)
    run_place(tracker, [hover(cell, alt=20.0)], 0.2)  # popped out of the window
    placed, _ = run_place(tracker, [hover(cell, alt=4.0)], PLACE_DWELL * 0.7)
    assert placed == [], "dwell restarted after leaving the window"


def test_place_cell_change_restarts():
    tm = TileMap()
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry)
    run_place(tracker, [hover((3, 3), alt=4.0)], PLACE_DWELL * 0.7)
    placed, _ = run_place(tracker, [hover((4, 3), alt=4.0)], PLACE_DWELL * 0.7)
    assert placed == [], "drifting to a neighbor cell restarts the dwell there"


def test_place_refused_outside_allowed_cells():
    tm = TileMap()
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry, allowed=lambda c: c == (9, 9))
    cell = (3, 3)
    placed, refused = run_place(tracker, [hover(cell, alt=4.0)], PLACE_DWELL + 0.3)
    assert placed == []
    assert refused and refused[0][1] == cell
    assert carry.item("d0") == "steel", "a refused placement keeps the tile"
    assert tm.height(cell) == 0


def test_place_refused_by_crush_rule():
    tm = TileMap()
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry)
    cell = (3, 3)
    bystander = hover(cell, alt=1.0, drone_id="d1")
    placed, refused = run_place(tracker, [hover(cell, alt=4.0), bystander],
                                PLACE_DWELL + 0.3)
    assert placed == []
    assert refused, "a drone under the new stack top blocks placement"


def test_place_refused_on_keep_out():
    tm = TileMap()
    pad = hex.axial_to_world((3, 3))
    tm.set_keep_out([pad])
    carry = CarrySlots()
    carry.give("d0", "steel")
    tracker = PlaceTracker(tm, carry)
    placed, refused = run_place(tracker, [hover((3, 3), alt=4.0)], PLACE_DWELL + 0.3)
    assert placed == [] and refused


# ------------------------------------------------------------- tick_sources

def run_sources(drones, sources, carry, seconds, dt=0.1):
    pickups = []
    for _ in range(int(round(seconds / dt))):
        pickups.extend(tick_sources(drones, sources, carry, dt))
    return pickups


def test_source_pickup_and_depletion():
    source = TileSource("quarry", 10.0, 10.0, "steel", remaining=2)
    carry = CarrySlots()
    d = view("d0", n=10.0, e=10.0, alt=2.0)
    pickups = run_sources([d], [source], carry, 3.0)
    assert len(pickups) == 1, "hands full after the first pickup"
    assert carry.item("d0") == "steel"
    assert source.remaining == 1

    carry.take("d0")
    pickups = run_sources([d], [source], carry, 3.0)
    assert len(pickups) == 1
    assert source.remaining == 0

    carry.take("d0")
    assert run_sources([d], [source], carry, 3.0) == [], "the pile is spent"
