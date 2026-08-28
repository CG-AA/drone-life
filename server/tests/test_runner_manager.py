"""RunnerManager local-mode lifecycle: logs pumped, exits observed, stop reaps.

Container mode is mocked here (podman lives in the e2e suite) — what these
pin is that a missing image fails the submit instead of the run.
"""

import asyncio

import pytest

from app.config import Settings
from app.core.registry import Student
from app.runner.manager import END_REASONS, Run, RunnerError, RunnerManager, end_reason


def make_student() -> Student:
    return Student(id="s0", name="Testy", token="t", slot=0, sysid=1, port=5760)


def make_manager(events: list, **overrides) -> RunnerManager:
    return RunnerManager(Settings(**overrides), examples_dir=None,
                         on_event=lambda sid, payload: events.append((sid, payload)))


def fake_image_probe(problem: str | None):
    async def _probe(self) -> str | None:
        return problem
    return _probe


async def _awaitable(value):
    """create_subprocess_exec is awaited, so a fake must be too."""
    return value


async def wait_for(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_local_run_pumps_logs_and_reports_exit(tmp_path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello from the script')\n")
    events: list = []
    mgr = make_manager(events)
    student = make_student()

    run_id = await mgr.submit_local(student, script)
    await wait_for(lambda: mgr.run_for("s0").state == "exited")

    run = mgr.run_for("s0")
    assert run.run_id == run_id
    assert run.exit_code == 0
    assert run.reason == "done"
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "stdout"]
    assert "hello from the script" in lines
    assert [p["state"] for _sid, p in events] == ["running", "exited"]
    system = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "system"]
    assert "script finished (exit 0)" in system

    # pumps and the exit watcher wound down by themselves
    await wait_for(lambda: all(t.done() for t in run.tasks))


async def test_stop_kills_and_reaps_tasks(tmp_path):
    script = tmp_path / "forever.py"
    script.write_text("import time\ntime.sleep(60)\n")
    events: list = []
    mgr = make_manager(events)
    student = make_student()

    await mgr.submit_local(student, script)
    run = mgr.run_for("s0")
    assert run.state == "running"

    assert await mgr.stop("s0") is True
    assert run.state == "exited"
    assert run.reason == "stopped"
    assert run.tasks == []  # cancelled-or-done and cleared, nothing left pending
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "system"]
    assert "stopped" in lines


async def test_resubmit_marks_the_old_run_replaced(tmp_path):
    forever = tmp_path / "forever.py"
    forever.write_text("import time\ntime.sleep(60)\n")
    quick = tmp_path / "quick.py"
    quick.write_text("print('second')\n")
    events: list = []
    mgr = make_manager(events)
    student = make_student()

    await mgr.submit_local(student, forever)
    first = mgr.run_for("s0")
    await mgr.submit_local(student, quick)

    assert first.reason == "replaced"
    assert mgr.run_for("s0") is not first
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "system"]
    assert "stopped — replaced by a new submit" in lines
    await mgr.stop_all()  # don't leave the replacement running past the test


async def test_timeout_says_it_hit_the_limit(tmp_path):
    script = tmp_path / "forever.py"
    script.write_text("import time\ntime.sleep(60)\n")
    events: list = []
    mgr = make_manager(events, run_max_seconds=1)
    student = make_student()

    await mgr.submit_local(student, script)
    await wait_for(lambda: mgr.run_for("s0").state == "exited", timeout=10.0)

    run = mgr.run_for("s0")
    assert run.reason == "timeout"
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "system"]
    assert "stopped: hit the 1s run limit" in lines
    assert events[-1][1]["reason"] == "timeout"


async def test_start_failure_reports_start_failed(tmp_path, monkeypatch):
    events: list = []
    mgr = make_manager(events)

    async def boom(*argv, **kwargs):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    with pytest.raises(RunnerError):
        await mgr.submit_local(make_student(), tmp_path / "whatever.py")

    run = mgr.run_for("s0")
    assert run.reason == "start_failed" and run.exit_code == -1
    assert events[-1][1]["reason"] == "start_failed"


def test_end_reason_maps_podman_failures_apart_from_script_errors():
    assert end_reason("container", 0) == "done"
    assert end_reason("container", 1) == "error"
    for code in (125, 126, 127):
        assert end_reason("container", code) == "runner_failed"
    # a local bot has no podman in the path: those codes are the script's own
    assert end_reason("local", 125) == "error"


async def test_submit_container_without_image_raises_runner_error(tmp_path, monkeypatch):
    events: list = []
    mgr = make_manager(events, state_dir=tmp_path / "state")
    monkeypatch.setattr(RunnerManager, "_image_probe",
                        fake_image_probe("runner image x is not built — run `make image`"))

    with pytest.raises(RunnerError, match="make image"):
        await mgr.submit_container(make_student(), "print('hi')\n")
    assert mgr.run_for("s0") is None  # nothing half-started, nothing to explain
    assert events == []


async def test_image_probe_caches_the_positive_only(tmp_path, monkeypatch):
    events: list = []
    mgr = make_manager(events, state_dir=tmp_path / "state")
    calls: list = []
    rc = [1]

    class FakeProc:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            FakeProc.returncode = self.returncode = rc[0]
            return b"", b""

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert "make image" in (await mgr._image_probe() or "")
    assert "make image" in (await mgr._image_probe() or "")  # negatives re-probe
    assert len(calls) == 2
    rc[0] = 0
    assert await mgr._image_probe() is None
    assert await mgr._image_probe() is None  # positive cached: an image can't un-build
    assert len(calls) == 3


async def test_a_broken_podman_is_not_reported_as_a_missing_image(tmp_path, monkeypatch):
    """The bug this exists for: a wrong XDG_RUNTIME_DIR made every submit say
    "run `make image`", the one fix that could not help. The two must read
    differently, and podman's own words must survive."""
    mgr = make_manager([], state_dir=tmp_path / "state")

    class FakeProc:
        returncode = 125

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"Error: XDG_RUNTIME_DIR=/run/user/1001 is not owned by you\n"

    monkeypatch.setattr(asyncio, "create_subprocess_exec",
                        lambda *a, **k: _awaitable(FakeProc()))
    problem = await mgr._image_probe()
    assert problem is not None
    assert "make image" not in problem
    assert "XDG_RUNTIME_DIR" in problem and "preflight" in problem
    assert not mgr._image_seen  # a podman failure must never cache as "fine"


async def test_a_podman_that_cannot_be_run_at_all_says_so(tmp_path, monkeypatch):
    mgr = make_manager([], state_dir=tmp_path / "state")

    def boom(*argv, **kwargs):
        raise FileNotFoundError("podman")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    problem = await mgr._image_probe()
    assert problem is not None and "preflight" in problem


async def test_every_end_reason_is_one_the_wire_knows(tmp_path):
    """Run.end is the only door out, and protocol.ts/runstate.ts mirror this
    list — an unregistered reason would render as a blank pill."""
    run = Run(run_id="r1", student_id="s0", mode="local")
    with pytest.raises(AssertionError, match="unregistered end reason"):
        run.end("exploded", 1)
    for reason in END_REASONS:
        Run(run_id="r1", student_id="s0", mode="local").end(reason, 0)
