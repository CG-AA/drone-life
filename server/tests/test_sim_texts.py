"""The upstream text channel in the sim: a script's STATUSTEXT lands in the
drone's inbox, bounded, and the world drains it for the engine."""

from app.sim.drone import INBOX_MAX
from app.sim.world import World


def test_hear_strips_trims_and_drops_empties():
    world = World()
    d = world.spawn("d0", "s0", "Ada", 0)
    d.hear("  wallet\x00\x00 ")
    d.hear("")
    d.hear("\x00")
    d.hear("x" * 80)
    assert d.inbox == ["wallet", "x" * 50]


def test_the_inbox_is_bounded():
    world = World()
    d = world.spawn("d0", "s0", "Ada", 0)
    for i in range(INBOX_MAX + 5):
        d.hear(f"buy {i}")
    assert len(d.inbox) == INBOX_MAX and d.inbox[-1] == f"buy {INBOX_MAX - 1}"


def test_drain_hands_every_text_to_the_engine_once():
    world = World()
    a = world.spawn("d0", "s0", "Ada", 0)
    b = world.spawn("d1", "s1", "Bo", 1)
    a.hear("wallet")
    b.hear("shop")
    b.hear("buy zap")
    assert world.drain_texts() == [(a, "wallet"), (b, "shop"), (b, "buy zap")]
    assert a.inbox == [] and b.inbox == []
    assert world.drain_texts() == []
