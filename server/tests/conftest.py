import os

os.environ["MAVLINK20"] = "1"  # must be set before mavutil is imported anywhere

import asyncio
from contextlib import asynccontextmanager

import pytest
from pymavlink import mavutil

from app.config import Settings
from app.headless import find_port_base
from app.main import create_app
from app.service import DroneLifeService

__all__ = ["Pilot", "find_port_base", "make_settings", "running_app"]


# find_port_base lives in app.headless (shared with the balance tool); the
# name stays importable from here for the tests that always used it


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
        # the console on the public side: the suite must not bind real admin
        # ports in every test — test_admin_port.py is where that happens
        admin_port=0,
    )
    base.update(overrides)
    return Settings(**base)


@asynccontextmanager
async def running_app(settings: Settings):
    """create_app under its own lifespan — the real bring-up/teardown order
    (service, hub, admin listener), not a copy of it. Shared by the API tests
    and the (marker-gated) e2e tests so they can't drift apart."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


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


# The mission-test harness (FakeWorld, view, assert_grammar) lives in
# tests/support/harness.py — importing from conftest is a pytest anti-pattern.
