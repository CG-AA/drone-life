"""RunnerManager local-mode lifecycle: logs pumped, exits observed, stop reaps."""

import asyncio

from app.config import Settings
from app.core.registry import Student
from app.runner.manager import RunnerManager


def make_student() -> Student:
    return Student(id="s0", name="Testy", token="t", slot=0, sysid=1, port=5760)


def make_manager(events: list) -> RunnerManager:
    return RunnerManager(Settings(), examples_dir=None,
                         on_event=lambda sid, payload: events.append((sid, payload)))


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
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "stdout"]
    assert "hello from the script" in lines
    assert [p["state"] for _sid, p in events] == ["running", "exited"]

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
    assert run.tasks == []  # cancelled-or-done and cleared, nothing left pending
    lines = [e["line"] for e in mgr.log_for("s0").tail(50) if e["stream"] == "system"]
    assert "stopped" in lines
