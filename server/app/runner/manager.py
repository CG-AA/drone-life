"""Script run lifecycle: one active run per student, kill+replace on resubmit,
wall-clock cap, live log pumping. Containers for students, plain subprocesses
for bots and tests (mode="local").
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..core.registry import Student
from .logs import RingLog
from .podman import container_argv

log = logging.getLogger(__name__)

RunEventCb = Callable[[str, dict], None]  # (student_id, run_state payload)

# Why a run ended. An exit code alone can't tell a student whether they were
# killed, timed out, or never started. protocol.ts mirrors this list and
# ui.test.ts pins it, so keep the one-per-line quoted format.
# BEGIN-END-REASONS
END_REASONS = (
    "done",          # exit 0
    "error",         # the script itself failed
    "timeout",       # hit run_max_seconds
    "stopped",       # student's stop button, admin kill, or a reset
    "replaced",      # superseded by a new submit
    "start_failed",  # the runner process never launched
    "runner_failed",  # podman failed, not the script
)
# END-END-REASONS

PODMAN_ERROR_CODES = (125, 126, 127)  # podman itself failed, not the student's script
IMAGE_MISSING_RC = 1  # `podman image exists`: 1 is "no such image", anything else is podman


class RunnerError(Exception):
    pass


def end_reason(mode: str, code: int) -> str:
    if code == 0:
        return "done"
    if mode == "container" and code in PODMAN_ERROR_CODES:
        return "runner_failed"
    return "error"


def end_line(reason: str, code: int | None, max_seconds: int) -> str:
    """The last line of a student's log: it has to say what happened."""
    if reason == "done":
        return "script finished (exit 0)"
    if reason == "timeout":
        return f"stopped: hit the {max_seconds}s run limit"
    if reason == "replaced":
        return "stopped — replaced by a new submit"
    if reason == "stopped":
        return "stopped"
    if reason == "runner_failed":
        return f"the sandbox failed to start (podman exit {code}) — tell your instructor"
    return f"script exited with an error (exit {code})"


@dataclass
class Run:
    run_id: str
    student_id: str
    mode: str  # "container" | "local"
    container: str | None = None
    proc: asyncio.subprocess.Process | None = None
    state: str = "starting"  # starting | running | exited
    exit_code: int | None = None
    reason: str | None = None  # why it ended; None while it hasn't — see END_REASONS
    tasks: list[asyncio.Task] = field(default_factory=list)  # pumps + exit watcher
    stopping: bool = False  # a deliberate stop is in flight: the exit watcher stays quiet

    def payload(self) -> dict:
        return {"run_id": self.run_id, "state": self.state, "exit_code": self.exit_code,
                "reason": self.reason}

    def end(self, reason: str, code: int | None) -> None:
        """The one place a run becomes "exited" — reasons the web mirror does not
        know would render as a blank pill, so they never leave here."""
        assert reason in END_REASONS, f"unregistered end reason {reason!r} — see END_REASONS"
        self.state = "exited"
        self.exit_code = code
        self.reason = reason


class RunnerManager:
    def __init__(self, settings: Settings, examples_dir: Path, on_event: RunEventCb) -> None:
        self.s = settings
        self.examples_dir = examples_dir
        self.on_event = on_event
        self.runs: dict[str, Run] = {}
        self.logs: dict[str, RingLog] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._image_seen = False

    def log_for(self, student_id: str) -> RingLog:
        return self.logs.setdefault(student_id, RingLog())

    def run_for(self, student_id: str) -> Run | None:
        return self.runs.get(student_id)

    def _lock(self, student_id: str) -> asyncio.Lock:
        return self._locks.setdefault(student_id, asyncio.Lock())

    # ------------------------------------------------------------- submitting

    async def _image_probe(self) -> str | None:
        """None when the image is there, else the sentence the submit fails with.

        `--pull=never` turns a missing image into an exit-125 container nobody
        reads, so probe first. A broken podman (wrong XDG_RUNTIME_DIR, missing
        subuid range) also fails this probe, and must not be reported as a
        missing image: the fixes are different and `make image` won't help.
        Only the positive is cached: `make image` mid-class fixes the next click.
        """
        if self._image_seen:
            return None
        try:
            p = await asyncio.create_subprocess_exec(
                "podman", "image", "exists", self.s.runner_image,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _out, err = await p.communicate()
        except OSError as exc:
            return f"podman could not be run ({exc}) — instructor: run `make preflight`"
        if p.returncode == 0:
            self._image_seen = True
            return None
        if p.returncode == IMAGE_MISSING_RC:
            return (f"runner image {self.s.runner_image} is not built "
                    "— instructor: run `make image`")
        tail = (err.decode(errors="replace").strip().splitlines() or ["no output"])[-1]
        log.error("podman probe failed (exit %s): %s", p.returncode, tail)
        return (f"podman is not working here (exit {p.returncode}: {tail}) "
                "— instructor: run `make preflight`, then check the journal")

    def _write_script(self, script_dir: Path, code: str) -> None:
        script_dir.mkdir(parents=True, exist_ok=True)
        script = script_dir / "current.py"
        script.write_text(code)
        script.chmod(0o644)  # rootless uid mapping: container user must be able to read it
        script_dir.chmod(0o755)

    async def submit_container(self, student: Student, code: str) -> str:
        problem = await self._image_probe()
        if problem is not None:
            raise RunnerError(problem)
        script_dir = self.s.abs_state_dir / "scripts" / student.id
        # off-loop: this runs on the request path the 20 Hz driver shares
        await asyncio.to_thread(self._write_script, script_dir, code)
        async with self._lock(student.id):
            await self._stop_locked(student.id, reason="replaced")
            run_id = uuid.uuid4().hex[:8]
            name = f"dl-{self.s.room_id}-{student.id}-{run_id}"  # s0 exists in every room
            argv = container_argv(self.s, student, name, script_dir)
            return await self._start(student, run_id, argv, mode="container", container=name)

    async def submit_local(self, student: Student, script_path: Path) -> str:
        """Bots and tests: run an example script as a plain subprocess."""
        async with self._lock(student.id):
            await self._stop_locked(student.id, reason="replaced")
            run_id = uuid.uuid4().hex[:8]
            env = dict(
                os.environ,
                DRONE_URL=f"tcp:{self.s.mavlink_host}:{student.port}",
                STUDENT_NAME=student.name,
                PYTHONPATH=str(self.examples_dir),
                PYTHONUNBUFFERED="1",
                MAVLINK20="1",  # the gateway speaks MAVLink 2 on the wire
            )
            argv = [sys.executable, str(script_path)]
            return await self._start(student, run_id, argv, mode="local", env=env)

    async def _start(self, student: Student, run_id: str, argv: list[str], mode: str,
                     container: str | None = None, env: dict | None = None) -> str:
        ring = self.log_for(student.id)
        run = Run(run_id=run_id, student_id=student.id, mode=mode, container=container)
        self.runs[student.id] = run
        try:
            run.proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            run.end("start_failed", -1)
            ring.append("system", f"failed to start: {exc}")
            self._emit(run)
            raise RunnerError(str(exc)) from exc
        run.state = "running"
        ring.append("system", f"run {run_id} started ({mode})")
        self._emit(run)
        assert run.proc.stdout is not None  # both PIPEd above
        assert run.proc.stderr is not None
        # retained: an unreferenced task can be GC'd mid-flight and its
        # exception would vanish until collection
        run.tasks = [
            asyncio.create_task(self._pump(run.proc.stdout, "stdout", ring),
                                name=f"pump-stdout-{run_id}"),
            asyncio.create_task(self._pump(run.proc.stderr, "stderr", ring),
                                name=f"pump-stderr-{run_id}"),
            asyncio.create_task(self._await_exit(student, run, ring),
                                name=f"await-exit-{run_id}"),
        ]
        for task in run.tasks:
            task.add_done_callback(log_task_crash)
        return run_id

    # --------------------------------------------------------------- runtime

    @staticmethod
    async def _pump(stream: asyncio.StreamReader, name: str, ring: RingLog) -> None:
        while True:
            try:
                line = await stream.readline()
            except ValueError:  # line longer than the reader limit: drop it, keep pumping
                ring.append("system", "…output line too long, dropped…")
                continue
            except OSError as exc:  # dead transport would loop hot on continue
                log.debug("log pump %s ended: %r", name, exc)
                return
            if not line:
                return
            ring.append(name, line.decode("utf-8", "replace").rstrip("\n"))

    async def _await_exit(self, student: Student, run: Run, ring: RingLog) -> None:
        assert run.proc is not None  # _start only spawns this after exec succeeds
        reason = None
        try:
            code = await asyncio.wait_for(run.proc.wait(), timeout=self.s.run_max_seconds)
        except TimeoutError:
            reason = "timeout"
            await self._kill(run)
            code = await run.proc.wait()
        if self.runs.get(student.id) is run and run.state != "exited" and not run.stopping:
            ended = reason or end_reason(run.mode, code)
            run.end(ended, code)
            if ended == "runner_failed":
                log.warning("run %s: podman exited %d — image or sandbox problem",
                            run.run_id, code)
            ring.append("system", end_line(ended, code, self.s.run_max_seconds))
            self._emit(run)

    async def _kill(self, run: Run) -> None:
        if run.mode == "container" and run.container:
            try:
                p = await asyncio.create_subprocess_exec(
                    "podman", "rm", "-f", "-t", "0", run.container,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await p.wait()
            except OSError:
                pass
        if run.proc and run.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                run.proc.kill()

    async def _stop_locked(self, student_id: str, reason: str = "stopped") -> bool:
        run = self.runs.get(student_id)
        if run is None or run.state == "exited":
            return False
        # the kill lands as exit 137 before we get to say why; without this the
        # student's log reads "exited with an error (exit 137)" above "stopped"
        run.stopping = True
        await self._kill(run)
        if run.proc:
            try:
                await asyncio.wait_for(run.proc.wait(), 10)
            except TimeoutError:
                log.warning("run %s did not die within 10s", run.run_id)
        run.end(reason, run.proc.returncode if run.proc else -1)
        self.log_for(student_id).append("system", end_line(reason, run.exit_code,
                                                           self.s.run_max_seconds))
        self._emit(run)
        if run.tasks:
            # brief grace so the pumps drain the pipes, then reap stragglers
            _done, pending = await asyncio.wait(run.tasks, timeout=1.0)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            run.tasks.clear()
        return True

    async def stop(self, student_id: str) -> bool:
        async with self._lock(student_id):
            return await self._stop_locked(student_id)

    async def stop_all(self) -> None:
        for student_id in list(self.runs):
            await self.stop(student_id)

    async def sweep(self) -> None:
        """Remove leftover containers from a previous server life (--rm leaks on SIGKILL).
        Only this room's: the other rooms on the box are alive and flying
        (docs/ROOMS.md) — `make kill-prod` is the sweep that takes everything."""
        try:
            p = await asyncio.create_subprocess_exec(
                "podman", "ps", "-aq", "--filter", f"label=drone-life-room={self.s.room_id}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await p.communicate()
        except OSError:
            return  # no podman on this box: container mode will fail loudly at submit
        ids = out.split()
        if ids:
            log.info("sweeping %d leftover containers", len(ids))
            p = await asyncio.create_subprocess_exec(
                "podman", "rm", "-f", *[i.decode() for i in ids],
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()

    def _emit(self, run: Run) -> None:
        try:
            self.on_event(run.student_id, run.payload())
        except Exception:
            log.exception("run event callback failed")


def log_task_crash(task: asyncio.Task) -> None:
    """A long-lived task that dies must say so — a strong reference keeps its
    exception from ever surfacing on its own. Used for the driver too."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("task %s crashed", task.get_name(), exc_info=exc)
