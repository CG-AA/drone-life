"""DroneLifeService: the whole game in one object, assembled once.

One asyncio event loop drives everything. The 20 Hz driver task steps the sim,
sends telemetry, and every 2nd tick runs the mission and broadcasts the world
snapshot. FastAPI (main.py) is a thin shell around this; tests use it directly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from .api import messages
from .config import Settings
from .core import snapshot
from .core.bus import EventBus
from .core.registry import Registry, RoomFullError, Student
from .game.engine import GameEngine
from .game.mission import MissionConfig
from .game.missions import MISSIONS
from .mav.gateway import Gateway
from .runner.manager import RunnerManager
from .sim import params as P
from .sim.backend import DroneBackend, DroneView
from .sim.drone import SEV_INFO
from .sim.world import World

log = logging.getLogger(__name__)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
BOT_SCRIPTS = {"bot_patrol", "bot_courier"}
SNAPSHOT_INTERVAL = 30.0


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
        self.world = World(seed=settings.sim_seed)
        self.gateway = Gateway(self.world, settings.mavlink_host, settings.mavlink_base_port)
        self.backend = KinematicBackend(self.world, self.gateway)
        self.bus = EventBus()
        self.registry = Registry(settings.max_students, settings.mavlink_base_port)
        self._bind_mission(settings)
        self.runner = RunnerManager(settings, EXAMPLES_DIR, self._on_run_event)
        self.hub = None  # set by api.ws when the app wires up

        self.ticks = 0
        self.overruns = 0
        self._pending_events: list[tuple[DroneView, str]] = []
        self._tasks: list[asyncio.Task] = []
        self._snapshot_path = settings.abs_state_dir / "snapshot.json"

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
            pads=[World.pad_position(i) for i in range(settings.max_students)],
        )
        self.engine = GameEngine(self.backend, self.bus, mission_cls(), config, settings.sim_seed)
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
        self._tasks = [
            asyncio.create_task(self._driver(), name="driver"),
            asyncio.create_task(self._snapshotter(), name="snapshotter"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.runner.stop_all()
        await self.gateway.stop_all()
        self._save_snapshot()

    async def _driver(self) -> None:
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        tick = 0
        while True:
            events = self.world.step(P.DT)
            self._pending_events.extend((DroneView.of(d), kind) for d, kind in events)
            await self.gateway.telemetry_tick(tick)
            if tick % 2 == 0:  # 10 Hz: mission + WS
                pending, self._pending_events = self._pending_events, []
                self.engine.tick(self.world.t, 2 * P.DT, pending)
                if self.hub is not None:
                    self.hub.broadcast_world(self.world_message())
                    if self.tilemap is not None and self.tilemap.version != self._tiles_sent:
                        self._tiles_sent = self.tilemap.version
                        self.hub.broadcast_tiles(self.tiles_message())
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

    async def _snapshotter(self) -> None:
        while True:
            await asyncio.sleep(SNAPSHOT_INTERVAL)
            self._save_snapshot()

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

    def health(self) -> dict:
        return {"ok": True, "drones": len(self.world.drones), "ticks": self.ticks,
                "overruns": self.overruns, "score": self.engine.score}

    # -------------------------------------------------------------- runner cb

    def _on_run_event(self, student_id: str, payload: dict) -> None:
        if self.hub is not None:
            self.hub.send_run_state(student_id, payload)
        if payload["state"] == "exited":
            student = self.registry.students.get(student_id)
            name = student.name if student else student_id
            self.bus.emit("script_exit", f"{name}'s script exited (code {payload['exit_code']})",
                          student_id=student_id, t=self.world.t)
