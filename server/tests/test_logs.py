"""The per-run log flood ceiling: a runaway print loop must not drown the hub."""

from app.runner.logs import MAX_LINE, NOTICE_INTERVAL, RingLog


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_log(**kwargs):
    clock = FakeClock()
    return RingLog(rate=5, burst=5, clock=clock, **kwargs), clock


def streams(log):
    return [entry["stream"] for entry in log.lines]


def test_normal_output_passes_through():
    log, _ = make_log()
    for i in range(5):
        log.append("stdout", f"line {i}")
    assert [entry["line"] for entry in log.lines] == [f"line {i}" for i in range(5)]


def test_flood_is_dropped_and_announced_once():
    log, _ = make_log()
    for i in range(50):
        log.append("stdout", f"spam {i}")
    kept = [entry for entry in log.lines if entry["stream"] == "stdout"]
    notices = [entry for entry in log.lines if entry["stream"] == "system"]
    assert len(kept) == 5, "burst passes, the rest is dropped"
    assert len(notices) == 1, "one notice per interval, not one per dropped line"
    assert "dropped" in notices[0]["line"]


def test_second_notice_waits_for_the_interval():
    log, clock = make_log()
    for _ in range(20):
        log.append("stdout", "spam")
    assert streams(log).count("system") == 1
    clock.advance(NOTICE_INTERVAL + 1)
    for _ in range(60):  # the refill lets a few through, then floods again
        log.append("stdout", "spam")
    assert streams(log).count("system") == 2


def test_system_lines_survive_a_flood():
    """Run lifecycle lines say why a run ended — dropping those blinds the student."""
    log, _ = make_log()
    for _ in range(50):
        log.append("stdout", "spam")
    log.append("system", "script exited (code 1)")
    assert log.lines[-1]["line"] == "script exited (code 1)"


def test_tokens_refill_over_time():
    log, clock = make_log()
    for _ in range(20):
        log.append("stdout", "spam")
    before = streams(log).count("stdout")
    clock.advance(1.0)  # rate=5 → five more lines of budget
    for i in range(5):
        log.append("stdout", f"after {i}")
    assert streams(log).count("stdout") == before + 5


def test_long_lines_are_still_truncated():
    log, _ = make_log()
    log.append("stdout", "x" * (MAX_LINE * 2))
    assert len(log.lines[-1]["line"]) == MAX_LINE


def test_tail_returns_the_most_recent():
    log, _ = make_log()
    for i in range(3):
        log.append("system", f"line {i}")
    assert [entry["line"] for entry in log.tail(2)] == ["line 1", "line 2"]
