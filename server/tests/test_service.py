"""The driver task must outlive any bug inside a tick — and when it can't
tick, /healthz has to say so. A frozen sim that reports healthy is the
worst failure mode there is: nobody looks until a room of students notice.
"""

import asyncio

import pytest

from app import service as service_module
from app.game.missions import MISSIONS
from app.service import DroneLifeService

from .conftest import make_settings
from .test_engine import BrokenMission


async def spin(seconds: float = 0.2) -> None:
    """Let the unthrottled driver run: it yields every tick."""
    await asyncio.sleep(seconds)


def feed_kinds(svc: DroneLifeService, kind: str) -> list[dict]:
    return [ev for ev in svc.bus.feed if ev["kind"] == kind]


@pytest.fixture
async def broken_service(tmp_path, monkeypatch):
    monkeypatch.setitem(MISSIONS, "broken", BrokenMission)
    svc = DroneLifeService(make_settings(tmp_path, mission="broken"))
    await svc.start()
    yield svc
    await svc.stop()


async def test_a_mission_that_raises_everywhere_cannot_stop_the_sim(broken_service):
    await broken_service.join("Zoe")  # drone events reach the mission too
    before = broken_service.ticks
    await spin()

    assert broken_service.ticks > before
    assert not broken_service._tasks[0].done()
    assert feed_kinds(broken_service, "mission_error")
    # the engine contains mission bugs, so the driver itself is still healthy
    assert broken_service.health()["ok"] is True


async def test_a_broken_world_step_is_contained_and_shows_up_in_healthz(service, monkeypatch):
    monkeypatch.setattr(service_module, "DRIVER_STALL_S", 0.05)

    def boom(dt):
        raise RuntimeError("world is on fire")

    monkeypatch.setattr(service.world, "step", boom)
    await spin()

    assert not service._tasks[0].done()  # still ticking, just failing
    assert service.driver_errors > 0
    assert len(feed_kinds(service, "mission_error")) == 1  # throttled, not 20 Hz of it
    health = service.health()
    assert health["ok"] is False and health["driver_alive"] is True
    assert health["last_tick_age_s"] >= 0.05

    monkeypatch.undo()  # world recovers: so must health
    await spin(0.1)
    assert service.health()["ok"] is True


async def test_a_broken_broadcast_does_not_kill_the_driver(service):
    class ExplodingHub:
        def broadcast_world(self, message):
            raise RuntimeError("hub is on fire")

        def broadcast_tiles(self, message):
            raise RuntimeError("hub is on fire")

        def send_run_state(self, student_id, payload):
            pass

    service.hub = ExplodingHub()
    before = service.ticks
    await spin()

    assert not service._tasks[0].done()
    assert service.ticks > before
    assert service.driver_errors > 0


async def test_a_listener_that_raises_cannot_kill_the_driver_either(service, monkeypatch):
    """The error path fans out to the WS hub. If that raise escaped the
    handler, the guard would only have moved where the sim dies."""
    def boom(dt):
        raise RuntimeError("world is on fire")

    def also_boom(event):
        raise RuntimeError("the feed is on fire too")

    monkeypatch.setattr(service.world, "step", boom)
    service.bus.subscribe(also_boom)
    before = service.ticks
    await spin()

    assert not service._tasks[0].done()
    assert service.ticks > before
    assert service.driver_errors > 0


async def test_healthz_reports_a_fresh_service_as_running(service):
    health = service.health()
    assert health["ok"] is True and health["driver_alive"] is True
    assert health["mission"] == "delivery" and health["students"] == 0
    assert health["driver_errors"] == 0 and health["uptime_s"] >= 0


async def test_a_dead_driver_is_never_reported_healthy(service):
    driver = service._tasks[0]
    driver.cancel()
    await asyncio.gather(driver, return_exceptions=True)

    health = service.health()
    assert health["driver_alive"] is False and health["ok"] is False
