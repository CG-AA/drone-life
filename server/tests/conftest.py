import os

os.environ["MAVLINK20"] = "1"  # must be set before mavutil is imported anywhere

import asyncio  # noqa: E402
import random  # noqa: E402
import socket  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402
from pymavlink import mavutil  # noqa: E402

from app.config import Settings  # noqa: E402
from app.game import hex  # noqa: E402
from app.main import create_app  # noqa: E402
from app.service import DroneLifeService  # noqa: E402


def find_port_base(count: int = 8) -> int:
    """A base with `count` consecutive free TCP ports on loopback."""
    for _ in range(60):
        base = random.randint(20000, 55000)
        socks = []
        try:
            for i in range(count):
                s = socket.socket()
                s.bind(("127.0.0.1", base + i))
                socks.append(s)
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise RuntimeError("no free port range found")


def make_settings(tmp_path, **overrides) -> Settings:
    """One place for test settings so every suite stays in sync."""
    base = dict(
        sim_unthrottled=True,
        mavlink_base_port=find_port_base(),
        state_dir=tmp_path / "state",
        room_code="test-room",
        admin_token="test-admin",
        max_students=6,
        sim_seed=7,
    )
    base.update(overrides)
    return Settings(**base)


@asynccontextmanager
async def running_app(settings: Settings):
    """create_app with the canonical bring-up/teardown order. Shared by the
    API tests and the (marker-gated) e2e tests so they can't drift apart."""
    app = create_app(settings)
    service = app.state.service
    await service.start()
    app.state.hub.start()
    try:
        yield app
    finally:
        await app.state.hub.stop()
        await service.stop()


@pytest.fixture
async def service(tmp_path):
    svc = DroneLifeService(make_settings(tmp_path))
    await svc.start()
    yield svc
    await svc.stop()


class Pilot:
    """A student's-eye view of a drone: blocking mavutil, exactly like their scripts.
    Every method is synchronous — call from async tests via asyncio.to_thread."""

    def __init__(self, port: int) -> None:
        self.conn = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}", retries=3)
        self.conn.wait_heartbeat(timeout=10)

    def cmd(self, command: int, p1: float = 0, p2: float = 0, p7: float = 0) -> None:
        self.conn.mav.command_long_send(
            self.conn.target_system, self.conn.target_component,
            command, 0, p1, p2, 0, 0, 0, 0, p7)

    def mode_guided(self) -> None:
        self.cmd(mavutil.mavlink.MAV_CMD_DO_SET_MODE,
                 mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4)

    def arm(self) -> None:
        self.cmd(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)

    def takeoff(self, alt: float) -> None:
        self.cmd(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, p7=alt)

    def goto(self, n: float, e: float, alt: float) -> None:
        self.conn.mav.set_position_target_local_ned_send(
            0, self.conn.target_system, self.conn.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED, 3576,
            n, e, -alt, 0, 0, 0, 0, 0, 0, 0, 0)

    def vel(self, vn: float, ve: float, vd: float = 0) -> None:
        self.conn.mav.set_position_target_local_ned_send(
            0, self.conn.target_system, self.conn.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED, 3527,
            0, 0, 0, vn, ve, vd, 0, 0, 0, 0, 0)

    def pos(self, timeout: float = 10):
        msg = self.conn.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=timeout)
        assert msg is not None, "no LOCAL_POSITION_NED received"
        return msg

    def wait_alt(self, alt: float, tol: float = 0.7, timeout: float = 30) -> None:
        deadline = _now() + timeout
        while _now() < deadline:
            if abs(-self.pos().z - alt) < tol:
                return
        raise TimeoutError(f"never reached altitude {alt}")

    def wait_arrival(self, n: float, e: float, tol: float = 1.0, timeout: float = 30) -> None:
        deadline = _now() + timeout
        while _now() < deadline:
            msg = self.pos()
            if abs(msg.x - n) < tol and abs(msg.y - e) < tol:
                return
        raise TimeoutError(f"never arrived at ({n}, {e})")

    def wait_ack(self, command: int, timeout: float = 10) -> int:
        deadline = _now() + timeout
        while _now() < deadline:
            msg = self.conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=timeout)
            if msg is not None and msg.command == command:
                return msg.result
        raise TimeoutError(f"no ack for command {command}")

    def wait_statustext(self, substring: str, timeout: float = 15) -> str:
        deadline = _now() + timeout
        while _now() < deadline:
            msg = self.conn.recv_match(type="STATUSTEXT", blocking=True, timeout=timeout)
            if msg is not None and substring in msg.text:
                return msg.text
        raise TimeoutError(f"no STATUSTEXT containing {substring!r}")

    def wait_armed_state(self, armed: bool, timeout: float = 20) -> None:
        deadline = _now() + timeout
        while _now() < deadline:
            msg = self.conn.recv_match(type="HEARTBEAT", blocking=True, timeout=timeout)
            if msg is None:
                continue
            is_armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            if is_armed == armed:
                return
        raise TimeoutError(f"armed never became {armed}")

    def close(self) -> None:
        self.conn.close()


def _now() -> float:
    import time

    return time.monotonic()


@pytest.fixture
async def pilot_factory(service):
    pilots: list[Pilot] = []

    async def make(name: str) -> tuple[Pilot, object]:
        student, _ = await service.join(name)
        pilot = await asyncio.to_thread(Pilot, student.port)
        pilots.append(pilot)
        return pilot, student

    yield make
    for p in pilots:
        p.close()


# --------------------------------------------------------------- mission tests
# Shared harness for testing missions through the WorldAPI seam — no MAVLink,
# no sim. Import as `from tests.conftest import FakeWorld, view`.

from app.game.mission import MissionConfig  # noqa: E402
from app.sim.backend import DroneView  # noqa: E402


def view(drone_id="d0", n=0.0, e=0.0, alt=1.0, armed=True, crashed=False) -> DroneView:
    return DroneView(
        id=drone_id, student_id=f"s-{drone_id}", name=drone_id.upper(), sysid=1,
        n=n, e=e, alt=alt, vn=0, ve=0, valt=0, yaw=0, mode="GUIDED",
        armed=armed, on_ground=False, crashed=crashed, connected=True,
    )


class FakeWorld:
    def __init__(self) -> None:
        self.rng = random.Random(1)
        self.config = MissionConfig(arena_half=100, alt_max=60, pads=[hex.pad_cell(0)])
        self.now = 0.0
        self.views: list[DroneView] = []
        self.events: list[tuple[str, str]] = []
        self.texts: list[tuple[str, str]] = []  # (target, text)
        self.score = 0

    def drones(self):
        return self.views

    def emit_event(self, kind, msg, student_id=None, data=None):
        self.events.append((kind, msg))

    def add_score(self, points, reason, student_id=None):
        self.score += points
        return self.score

    def send_text(self, drone_id, text, severity=6):
        self.texts.append((drone_id, text))

    def broadcast_text(self, text, severity=6):
        self.texts.append(("*", text))

    def run(self, mission, seconds, dt=0.1):
        for _ in range(int(seconds / dt)):
            self.now += dt
            mission.tick(self, dt)
