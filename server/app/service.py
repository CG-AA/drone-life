"""DroneLifeService: the whole game in one object, assembled once.

One asyncio event loop drives everything. The 20 Hz driver task steps the sim,
sends telemetry, and every 2nd tick runs the mission and broadcasts the world
snapshot. FastAPI (main.py) is a thin shell around this; tests use it directly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .api import messages
from .config import Settings
from .core import snapshot
from .core.bus import EventBus
from .core.registry import Registry, RoomFullError, Student
from .game import hex
from .game.engine import GameEngine
from .game.mission import MissionConfig
from .game.missions import MISSIONS
from .mav.gateway import Gateway
from .runner.manager import RunnerManager, log_task_crash
from .sim import params as P
from .sim.backend import DroneBackend, DroneView
from .sim.drone import SEV_INFO
from .sim.world import World

if TYPE_CHECKING:
    from .api.ws import Hub

log = logging.getLogger(__name__)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
BOT_SCRIPTS = {"bot_patrol", "bot_courier", "bot_builder", "bot_siege"}
SNAPSHOT_INTERVAL = 30.0
MISSION_EVERY = P.TICK_HZ // P.MISSION_HZ  # mission + WS run every Nth sim tick
DRIVER_ERROR_EVERY = 30.0  # a 20 Hz bug must not flood the feed (cf. engine.py)
DRIVER_STALL_S = 5.0  # no successful tick for this long: the sim is not running

# What the projector says when a run ends. "exit -9" means nothing across a room.
EXIT_PHRASE = {
    "done": "finished",
    "timeout": "hit the time limit",
    "stopped": "was stopped",
    "start_failed": "could not start",
    "runner_failed": "hit a sandbox problem — instructor needed",
}


class KinematicBackend(DroneBackend):
    """v1 drone backend: our kinematic sim + MAVLink gateway."""

    def __init__(self, world: World, gateway: Gateway) -> None:
        self.world = world
        self.gateway = gateway

    async def spawn(self, drone_id: str, student_id: str, name: str, slot: int) -> DroneView:
        drone = self.world.spawn(drone_id, student_id, name, slot)
        await self.gateway.start_listener(drone, slot)
        return DroneView.of(drone)

    async def remove(self, drone_id: str) -> None:
        await self.gateway.stop_listener(drone_id)
        self.world.remove(drone_id)

    def drones(self) -> Sequence[DroneView]:
        return [DroneView.of(d) for d in self.world.drones.values()]

    def send_text(self, drone_id: str, text: str, severity: int = SEV_INFO) -> None:
        drone = self.world.drones.get(drone_id)
        if drone:
            drone.say(text, severity)


class DroneLifeService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.world = World()
        self.gateway = Gateway(self.world, settings.mavlink_host, settings.mavlink_base_port)
        self.backend = KinematicBackend(self.world, self.gateway)
        self.bus = EventBus()
        self.registry = Registry(settings.max_students, settings.mavlink_base_port)
        self._bind_mission(settings)
        self.runner = RunnerManager(settings, EXAMPLES_DIR, self._on_run_event)
        self.hub: Hub | None = None  # set by api.ws when the app wires up

        self.ticks = 0
        self.overruns = 0
        self.driver_errors = 0
        self._pending_events: list[tuple[DroneView, str]] = []
        self._tasks: list[asyncio.Task] = []
        self._snapshot_path = settings.abs_state_dir / "snapshot.json"
        self._started_at = time.monotonic()
        self._last_tick = self._started_at
        self._last_driver_error = float("-inf")

    def _bind_mission(self, settings: Settings) -> None:
        """Instantiate the mission and wire it to the sim and broadcast state.
        One place, so a future runtime mission-switch is a route, not a
        rewiring project."""
        mission_cls = MISSIONS.get(settings.mission)
        if mission_cls is None:
            raise ValueError(f"unknown MISSION={settings.mission!r}; have {sorted(MISSIONS)}")
        config = MissionConfig(
            arena_half=P.ARENA_HALF,
            alt_max=P.ALT_MAX,
            pads=[hex.pad_cell(i) for i in range(settings.max_students)],
        )
        self.engine = GameEngine(self.backend, self.bus, mission_cls(), config, settings.sim_seed)
        # deliberately unguarded: a broken tile_map() should fail the boot loudly
        # before a workshop, not surface as a mid-session mission_error
        self.tilemap = self.engine.mission.tile_map()
        if self.tilemap is not None:
            self.world.terrain = self.tilemap
        self._tiles_sent = -1

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self.settings.abs_state_dir.mkdir(parents=True, exist_ok=True)
        data = snapshot.load(self._snapshot_path)
        if data:
            self.registry.restore(data.get("students", []))
            self.engine.score = int(data.get("score", 0))
            log.info("restored %d students, score %d",
                     len(self.registry.students), self.engine.score)
        for student in self.registry.students.values():
            await self._spawn_drone(student)
        self.engine.start(self.world.t)
        await self.runner.sweep()
        self._started_at = self._last_tick = time.monotonic()
        self._tasks = [
            asyncio.create_task(self._driver(), name="driver"),
            asyncio.create_task(self._snapshotter(), name="snapshotter"),
        ]
        for task in self._tasks:
            task.add_done_callback(log_task_crash)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.runner.stop_all()
        await self.gateway.stop_all()
        self._save_snapshot()

    async def _tick_once(self, tick: int) -> None:
        events = self.world.step(P.DT)
        self._pending_events.extend((DroneView.of(d), kind) for d, kind in events)
        await self.gateway.telemetry_tick(tick)
        if tick % MISSION_EVERY == 0:  # MISSION_HZ: mission + WS
            pending, self._pending_events = self._pending_events, []
            self.engine.tick(self.world.t, MISSION_EVERY * P.DT, pending)
            if self.hub is not None:
                self.hub.broadcast_world(self.world_message())
                if self.tilemap is not None and self.tilemap.version != self._tiles_sent:
                    self._tiles_sent = self.tilemap.version
                    self.hub.broadcast_tiles(self.tiles_message())

    def _driver_error(self) -> None:
        """A bug anywhere in the tick used to kill this task outright: the sim
        froze, nothing was logged, and /healthz still said ok. Keep ticking,
        say so on the feed, and let healthz go stale if it never recovers."""
        self.driver_errors += 1
        now = time.monotonic()
        if now - self._last_driver_error < DRIVER_ERROR_EVERY:
            return
        self._last_driver_error = now
        log.exception("driver tick failed")
        try:
            self.bus.emit("mission_error", "sim error — check server logs", t=self.world.t)
        except Exception:  # emit fans out to the hub: the last defence can't raise either
            log.exception("could not put the driver error on the feed")

    async def _driver(self) -> None:
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        tick = 0
        while True:
            try:
                await self._tick_once(tick)
            except Exception:
                self._driver_error()
            else:
                self._last_tick = time.monotonic()
            tick += 1
            self.ticks += 1
            next_t += P.DT
            if self.settings.sim_unthrottled:
                await asyncio.sleep(0)
                next_t = loop.time()
            else:
                delay = next_t - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    self.overruns += 1
                    if delay < -1.0:  # fell far behind (laptop slept?): resync
                        next_t = loop.time()
                    # nothing above is guaranteed to suspend, so a sustained
                    # overrun would otherwise starve HTTP/WS/runner tasks
                    await asyncio.sleep(0)

    async def _snapshotter(self) -> None:
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            try:
                self._save_snapshot()
            except Exception:  # one bad write must not end snapshots for the day
                log.exception("snapshot failed")

    def _save_snapshot(self) -> None:
        snapshot.save(self._snapshot_path, {
            "students": self.registry.to_dict(),
            "score": self.engine.score,
        })

    # ---------------------------------------------------------------- joins

    @staticmethod
    def drone_id_for(student: Student) -> str:
        return f"d{student.slot}"

    async def join(self, name: str) -> tuple[Student, bool]:
        student, is_new = self.registry.join(name)
        if is_new:
            await self._spawn_drone(student)
            self.bus.emit("joined", f"{student.name} joined the sky",
                          student_id=student.id, t=self.world.t)
            self._pending_events.append(
                (DroneView.of(self.world.drones[self.drone_id_for(student)]), "joined"))
        self._save_snapshot()
        return student, is_new

    async def _spawn_drone(self, student: Student) -> None:
        await self.backend.spawn(self.drone_id_for(student), student.id, student.name,
                                 student.slot)

    async def kick(self, student_id: str) -> bool:
        student = self.registry.remove(student_id)
        if student is None:
            return False
        await self.runner.stop(student_id)
        await self.backend.remove(self.drone_id_for(student))
        self.bus.emit("kicked", f"{student.name} left", student_id=student_id, t=self.world.t)
        self._save_snapshot()
        return True

    # ---------------------------------------------------------------- resets

    async def reset_mine(self, student: Student) -> None:
        await self.runner.stop(student.id)
        drone = self.world.drones.get(self.drone_id_for(student))
        if drone:
            drone.reset_to_pad()
        self.bus.emit("reset_mine", f"{student.name} reset their drone",
                      student_id=student.id, t=self.world.t)

    async def reset_world(self) -> None:
        await self.runner.stop_all()
        # bots are session furniture: clear them so `make reset && make bots`
        # really is a clean slate and bot numbering restarts at 1
        for student in list(self.registry.students.values()):
            if student.name.startswith("Bot-"):
                self.registry.remove(student.id)
                await self.backend.remove(self.drone_id_for(student))
        self.world.reset()
        self.engine.reset(self.world.t)
        self._save_snapshot()

    # ------------------------------------------------------------------ bots

    async def spawn_bots(self, count: int, script: str, mode: str) -> dict:
        """Returns {"started": [ids], "room_full": bool} — partial success is
        reported, never discarded, so the operator can see what's flying."""
        if script not in BOT_SCRIPTS:
            raise ValueError(f"unknown bot script {script!r}; have {sorted(BOT_SCRIPTS)}")
        script_path = EXAMPLES_DIR / f"{script}.py"
        code = script_path.read_text() if mode == "container" else None
        started: list[str] = []
        room_full = False
        # continue numbering past existing bots so repeat calls grow the fleet
        existing = [s.name for s in self.registry.students.values()
                    if s.name.startswith("Bot-")]
        next_no = max((int(n.split("-")[1]) for n in existing
                       if n.split("-")[1].isdigit()), default=0) + 1
        for i in range(count):
            try:
                student, _ = await self.join(f"Bot-{next_no + i}")
            except RoomFullError:
                room_full = True
                break
            if mode == "container":
                assert code is not None  # read above, exactly for this mode
                await self.runner.submit_container(student, code)
            else:
                await self.runner.submit_local(student, script_path)
            started.append(student.id)
        return {"started": started, "room_full": room_full}

    # ------------------------------------------------------------- messages
    # Wire shapes live in api/messages.py; these delegates keep the service
    # as the single facade for callers and tests.

    def world_message(self) -> dict:
        return messages.world_message(self)

    def hello_message(self) -> dict:
        return messages.hello_message(self)

    def tiles_message(self) -> dict:
        return messages.tiles_message(self)

    def hex_size(self) -> float:
        """The lattice pads and landmarks sit on — the tile map's if the
        mission has one, so the viewer draws the same grid either way."""
        return self.tilemap.size if self.tilemap is not None else hex.HEX_SIZE

    def health(self) -> dict:
        """`ok` means the sim is actually running — a frozen driver used to
        report healthy forever. Environment checks belong to `make preflight`."""
        age = time.monotonic() - self._last_tick
        alive = bool(self._tasks) and not self._tasks[0].done()
        return {"ok": alive and age < DRIVER_STALL_S,
                "drones": len(self.world.drones), "ticks": self.ticks,
                "overruns": self.overruns, "score": self.engine.score,
                "mission": self.engine.mission.name, "students": len(self.registry.students),
                "uptime_s": round(time.monotonic() - self._started_at, 1),
                "driver_alive": alive, "last_tick_age_s": round(age, 2),
                "driver_errors": self.driver_errors}

    # -------------------------------------------------------------- runner cb

    def _on_run_event(self, student_id: str, payload: dict) -> None:
        if self.hub is not None:
            self.hub.send_run_state(student_id, payload)
        if payload["state"] != "exited":
            return
        reason = payload["reason"]
        if reason == "replaced":
            return  # the new run's own lines say it better; don't spam the feed
        student = self.registry.students.get(student_id)
        name = student.name if student else student_id
        # "error" keeps its code: that number is the student's debugging handle
        phrase = EXIT_PHRASE.get(reason, f"exited (code {payload['exit_code']})")
        self.bus.emit("script_exit", f"{name}'s script {phrase}",
                      student_id=student_id, t=self.world.t)
