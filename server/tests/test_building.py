"""Building primitives: dwell, carry, placement — the reusable mechanics."""

from dataclasses import replace

from app.game import hex
from app.game.building import (
    HINT_EVERY,
    HINT_SUSTAIN,
    PLACE_CLEAR,
    PLACE_DWELL,
    PLACE_WINDOW,
    STUCK_S,
    TOO_HIGH_SAY,
    CarrySlots,
    DwellTracker,
    HintThrottle,
    HoverHint,
    PlaceHints,
    PlaceTracker,
    SourceHints,
    TileSource,
    crush_ok,
    fmt_cell,
    hover_alt_hint,
    place_window,
    tick_sources,
)
from app.game.tiles import TILE_HEIGHT, TileMap
from tests.support.harness import FakeWorld, view


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
    assert tracker.acc == {}, "winning resets the winner's timer"


def test_dwell_second_drone_keeps_its_progress():
    tracker = DwellTracker(radius=2.0, max_alt=3.0, dwell_s=1.0)
    a, b = view("d0"), view("d1")
    # d0 starts 0.3 s ahead; when it wins, d1's progress must survive
    tracker.update([a], 0, 0, 0.3)
    winner = run_dwell(tracker, [a, b], 0, 0, 1.0)
    assert winner is a
    assert tracker.acc.get("d1", 0) > 0.5, "the runner-up keeps accumulating"
    assert run_dwell(tracker, [b], 0, 0, 0.4) is b, "and finishes on schedule"


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
    for _ in range(round(seconds / dt)):
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
    for _ in range(round(seconds / dt)):
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


# --------------------------------------------------------------------- hints

def run_hint(world, hint, drones, n, e, seconds, dt=0.1):
    for _ in range(int(seconds / dt)):
        world.now += dt
        hint.tick(world, drones, n, e, dt)


def test_hint_throttle_gates_per_key():
    th = HintThrottle(every=10.0)
    assert th.ready("high:d0", 0.0)
    assert not th.ready("high:d0", 5.0)
    assert th.ready("full:d0", 5.0), "other hint kinds have their own clock"
    assert th.ready("high:d0", 10.0)


def test_hover_hint_needs_sustain_then_throttles():
    world = FakeWorld()
    hint = HoverHint(2.0, lambda d: d.alt > 3.0, TOO_HIGH_SAY, "high", HintThrottle())
    d = view(alt=10.0)
    run_hint(world, hint, [d], 0, 0, HINT_SUSTAIN * 0.7)
    assert world.texts == [], "a moment of wrongness is not worth a nag"
    run_hint(world, hint, [d], 0, 0, HINT_SUSTAIN)
    assert world.texts == [("d0", TOO_HIGH_SAY)]
    run_hint(world, hint, [d], 0, 0, HINT_SUSTAIN + 0.2)
    assert len(world.texts) == 1, "no re-nag inside the throttle window"
    run_hint(world, hint, [d], 0, 0, HINT_EVERY)
    assert len(world.texts) == 2, "a persistent offender is re-nagged"


def test_hover_hint_ignores_transiting_drone():
    world = FakeWorld()
    hint = HoverHint(2.0, lambda d: True, TOO_HIGH_SAY, "high", HintThrottle())
    d = view(alt=10.0)
    run_hint(world, hint, [d], 0, 0, HINT_SUSTAIN * 0.7)  # crosses the circle...
    run_hint(world, hint, [d], 50, 50, 0.3)  # ...and is gone before sustain
    run_hint(world, hint, [d], 0, 0, HINT_SUSTAIN * 0.7)  # crosses again
    assert world.texts == [], "leaving the circle resets the sustain clock"


def test_source_hints_speak_both_ways():
    world = FakeWorld()
    carry = CarrySlots()
    hints = SourceHints(carry, "GAME: hands full, place on the wall")
    too_high = view("d0", n=0.0, e=0.0, alt=10.0)
    run_hint(world, hints, [too_high], 0, 0, HINT_SUSTAIN + 0.2)
    assert ("d0", TOO_HIGH_SAY) in world.texts
    carry.give("d1", "steel")
    full = view("d1", n=0.0, e=0.0, alt=1.0)
    run_hint(world, hints, [full], 0, 0, HINT_SUSTAIN + 0.2)
    assert ("d1", "GAME: hands full, place on the wall") in world.texts


def run_place_hints(world, hints, drones, seconds, dt=0.1):
    for _ in range(int(seconds / dt)):
        world.now += dt
        hints.tick(world, drones, dt)


def test_place_hint_when_hovering_out_of_band():
    world, tm, carry = FakeWorld(), TileMap(), CarrySlots()
    hints = PlaceHints(tm, carry, HintThrottle())
    carry.give("d0", "steel")
    d = view(alt=20.0)  # way above the empty cell's placement band
    run_place_hints(world, hints, [d], STUCK_S + 0.2)
    hint = hover_alt_hint(tm, hex.world_to_axial(d.n, d.e))
    assert (f"GAME: hover {hint} m to place" in [t for _, t in world.texts])


def test_place_hint_silent_while_moving():
    world, tm, carry = FakeWorld(), TileMap(), CarrySlots()
    hints = PlaceHints(tm, carry, HintThrottle())
    carry.give("d0", "steel")
    d = replace(view(alt=20.0), vn=2.0)  # transiting, not trying to place
    run_place_hints(world, hints, [d], STUCK_S + 0.2)
    assert world.texts == []


def test_place_hint_silent_over_keepout():
    world, tm, carry = FakeWorld(), TileMap(), CarrySlots()
    tm.set_keep_out([(0.0, 0.0)])
    hints = PlaceHints(tm, carry, HintThrottle())
    carry.give("d0", "steel")
    d = view(alt=20.0)  # over the keep-out cell: no altitude would work
    run_place_hints(world, hints, [d], STUCK_S + 0.2)
    assert world.texts == []


def test_tick_ferry_flavours_texts_by_material_and_returns_pickups():
    from app.game.building import FerryTexts, tick_ferry

    world = FakeWorld()
    carry = CarrySlots()
    steel = TileSource("quarry", 0.0, 0.0, material="steel")
    clay = TileSource("pit", 30.0, 0.0, material="clay")
    texts = {"steel": FerryTexts("steel", "GAME: steel lost", "GAME: got steel", "GAME: full"),
             "clay": FerryTexts("clay", "GAME: clay lost", "GAME: got clay", "GAME: full")}
    world.views = [view("d0", n=0.0, e=0.0, alt=2.0), view("d1", n=30.0, e=0.0, alt=2.0)]
    got = []
    for _ in range(25):
        world.now += 0.1
        got += tick_ferry(world, world.views, carry, [steel, clay], 0.1, texts["steel"],
                          texts_by_material=texts)
    assert sorted((d.id, s.material) for d, s in got) == [("d0", "steel"), ("d1", "clay")]
    assert ("d1", "GAME: got clay") in world.texts and ("d0", "GAME: got steel") in world.texts
    world.views = [view("d1", n=30.0, e=0.0, alt=2.0, crashed=True)]
    tick_ferry(world, world.views, carry, [steel, clay], 0.1, texts["steel"],
               texts_by_material=texts)
    assert ("*", "GAME: clay lost") in world.texts


def test_dwell_tracker_takes_per_drone_reach_and_dwell():
    tracker = DwellTracker(radius=2.0, max_alt=3.0, dwell_s=1.0,
                           radius_of=lambda d: 5.0 if d.id == "far" else 2.0,
                           dwell_of=lambda d: 0.5 if d.id == "far" else 1.0)
    near = view("near", n=1.5, e=0.0, alt=2.0)
    far = view("far", n=4.0, e=0.0, alt=2.0)
    winners = []
    for _ in range(10):
        w = tracker.update([near, far], 0.0, 0.0, 0.1)
        winners.append(w.id if w else None)
    assert winners[4] == "far", "5 m reach, 0.5 s dwell: first"
    assert winners[9] == "near", "2 m reach, 1.0 s dwell: second"
