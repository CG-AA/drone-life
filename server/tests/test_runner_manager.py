"""RunnerManager local-mode lifecycle: logs pumped, exits observed, stop reaps.

Container mode is mocked here (podman lives in the e2e suite) — what these
pin is that a missing image fails the submit instead of the run.
"""

import asyncio

import pytest

from app.config import Settings
from app.core.registry import Student
from app.runner.manager import RunnerError, RunnerManager, end_reason


def make_student() -> Student:
    return Student(id="s0", name="Testy", token="t", slot=0, sysid=1, port=5760)


def make_manager(events: list, **overrides) -> RunnerManager:
    return RunnerManager(Settings(**overrides), examples_dir=None,
                         on_event=lambda sid, payload: events.append((sid, payload)))


def fake_image_probe(available: bool):
    async def _probe(self) -> bool:
        return available
    return _probe


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
    monkeypatch.setattr(RunnerManager, "_image_ok", fake_image_probe(False))

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
        async def wait(self) -> int:
            return rc[0]

    async def fake_exec(*argv, **kwargs):
        calls.append(argv)
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await mgr._image_ok() is False
    assert await mgr._image_ok() is False  # negatives re-probe: `make image` must land
    assert len(calls) == 2
    rc[0] = 0
    assert await mgr._image_ok() is True
    assert await mgr._image_ok() is True  # positive cached: an image can't un-build
    assert len(calls) == 3
