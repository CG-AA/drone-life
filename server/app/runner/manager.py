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


class RunnerError(Exception):
    pass


@dataclass
class Run:
    run_id: str
    student_id: str
    mode: str  # "container" | "local"
    container: str | None = None
    proc: asyncio.subprocess.Process | None = None
    state: str = "starting"  # starting | running | exited
    exit_code: int | None = None
    tasks: list[asyncio.Task] = field(default_factory=list)  # pumps + exit watcher

    def payload(self) -> dict:
        return {"run_id": self.run_id, "state": self.state, "exit_code": self.exit_code}


class RunnerManager:
    def __init__(self, settings: Settings, examples_dir: Path, on_event: RunEventCb) -> None:
        self.s = settings
        self.examples_dir = examples_dir
        self.on_event = on_event
        self.runs: dict[str, Run] = {}
        self.logs: dict[str, RingLog] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def log_for(self, student_id: str) -> RingLog:
        return self.logs.setdefault(student_id, RingLog())

    def run_for(self, student_id: str) -> Run | None:
        return self.runs.get(student_id)

    def _lock(self, student_id: str) -> asyncio.Lock:
        return self._locks.setdefault(student_id, asyncio.Lock())

    # ------------------------------------------------------------- submitting

    async def submit_container(self, student: Student, code: str) -> str:
        script_dir = self.s.abs_state_dir / "scripts" / student.id
        script_dir.mkdir(parents=True, exist_ok=True)
        script = script_dir / "current.py"
        script.write_text(code)
        script.chmod(0o644)  # rootless uid mapping: container user must be able to read it
        script_dir.chmod(0o755)
        async with self._lock(student.id):
            await self._stop_locked(student.id)
            run_id = uuid.uuid4().hex[:8]
            name = f"dl-{student.id}-{run_id}"
            argv = container_argv(self.s, student, name, script_dir)
            return await self._start(student, run_id, argv, mode="container", container=name)

    async def submit_local(self, student: Student, script_path: Path) -> str:
        """Bots and tests: run an example script as a plain subprocess."""
        async with self._lock(student.id):
            await self._stop_locked(student.id)
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
        except (FileNotFoundError, OSError) as exc:
            run.state = "exited"
            run.exit_code = -1
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
            task.add_done_callback(_log_task_crash)
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
        try:
            code = await asyncio.wait_for(run.proc.wait(), timeout=self.s.run_max_seconds)
        except TimeoutError:
            ring.append("system", f"run exceeded {self.s.run_max_seconds}s — stopping")
            await self._kill(run)
            code = await run.proc.wait()
        if self.runs.get(student.id) is run and run.state != "exited":
            run.state = "exited"
            run.exit_code = code
            ring.append("system", f"script exited (code {code})")
            self._emit(run)

    async def _kill(self, run: Run) -> None:
        if run.mode == "container" and run.container:
            try:
                p = await asyncio.create_subprocess_exec(
                    "podman", "rm", "-f", "-t", "0", run.container,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await p.wait()
            except (FileNotFoundError, OSError):
                pass
        if run.proc and run.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                run.proc.kill()

    async def _stop_locked(self, student_id: str) -> bool:
        run = self.runs.get(student_id)
        if run is None or run.state == "exited":
            return False
        await self._kill(run)
        if run.proc:
            try:
                await asyncio.wait_for(run.proc.wait(), 10)
            except TimeoutError:
                log.warning("run %s did not die within 10s", run.run_id)
        run.state = "exited"
        run.exit_code = run.proc.returncode if run.proc else -1
        self.log_for(student_id).append("system", "stopped")
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
        """Remove leftover containers from a previous server life (--rm leaks on SIGKILL)."""
        try:
            p = await asyncio.create_subprocess_exec(
                "podman", "ps", "-aq", "--filter", "label=drone-life=1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await p.communicate()
        except (FileNotFoundError, OSError):
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


def _log_task_crash(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("runner task %s crashed", task.get_name(), exc_info=exc)
