"""First-five-minutes check: the unedited starter template must be a visible
win — arm, climb, a move the projector shows, a clean landing — on the day's
opening mission (freefly), the teaching game (delivery) and the main event
(siege). Real subprocess, real MAVLink, unthrottled sim; this is the flight
every student's first Run performs. The siege starter gets the same treatment:
unedited, it must take off, fly to its guard post and start hunting.
"""

import asyncio
import time

import pytest

from app.service import EXAMPLES_DIR, DroneLifeService
from tests.conftest import make_settings

FLIGHT_BUDGET_S = 90  # wall clock; unthrottled it finishes in a few seconds


async def wait_for(deadline: float, predicate, what: str) -> None:
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    pytest.fail(f"template flight never {what}")


@pytest.mark.parametrize("mission", ["freefly", "delivery", "siege"])
async def test_template_unedited_is_a_visible_win(tmp_path, mission):
    settings = make_settings(tmp_path, mission=mission)
    service = DroneLifeService(settings)
    await service.start()
    try:
        student, _ = await service.join("Template-Kid")
        await service.runner.submit_local(student, EXAMPLES_DIR / "template.py")
        drone_id = service.drone_id_for(student)

        def snap():
            return next(v for v in service.backend.drones() if v.id == drone_id)

        deadline = time.monotonic() + FLIGHT_BUDGET_S
        await wait_for(deadline, lambda: snap().armed, "armed")
        await wait_for(deadline, lambda: snap().alt > 5.0, "climbed in view")
        # the destination is random per run (so a room's landings spread out
        # instead of stacking on one hex): the template picks north 10..40,
        # east -30..30 — far from the pad row at N -90
        await wait_for(deadline, lambda: snap().n > 7.5, "flew north into the arena")
        await wait_for(deadline, lambda: snap().on_ground and snap().n > 7.5,
                       "landed in view")
        spot = snap()
        assert 7.5 <= spot.n <= 42.5 and -32.5 <= spot.e <= 32.5, \
            f"landed outside the template's spread box: ({spot.n:.1f}, {spot.e:.1f})"
        await wait_for(deadline,
                       lambda: (r := service.runner.run_for(student.id)) is not None
                       and r.state == "exited",
                       "exited")
        run = service.runner.run_for(student.id)
        assert run is not None and run.exit_code == 0, \
            f"template exited {run and run.exit_code}: " \
            f"{service.runner.log_for(student.id).tail(10)}"
        final = snap()
        assert final.on_ground and not final.armed and not final.crashed, \
            "the template must end with a clean landing"
    finally:
        await service.stop()


async def test_siege_starter_unedited_hunts(tmp_path):
    """Unthrottled, the 45 s grace is over within a wall-second, so the guard
    post is a blink; what must hold is that the unedited starter arms, climbs
    into view, hears the creep callouts and settles into the zap loop at hunt
    altitude — still running, no traceback."""
    settings = make_settings(tmp_path, mission="siege")
    service = DroneLifeService(settings)
    await service.start()
    try:
        student, _ = await service.join("Siege-Kid")
        await service.runner.submit_local(student, EXAMPLES_DIR / "template_siege.py")
        drone_id = service.drone_id_for(student)

        def snap():
            return next(v for v in service.backend.drones() if v.id == drone_id)

        def log_text() -> str:
            return "\n".join(line["line"] for line in
                             service.runner.log_for(student.id).tail(200))

        deadline = time.monotonic() + FLIGHT_BUDGET_S
        await wait_for(deadline, lambda: snap().armed, "armed")
        await wait_for(deadline, lambda: snap().alt > 4.0, "climbed in view")
        await wait_for(deadline, lambda: "creep at N" in log_text(), "heard a creep callout")
        await wait_for(deadline, lambda: abs(snap().alt - 2.0) < 0.7 and not snap().on_ground,
                       "dropped to hunt altitude")
        run = service.runner.run_for(student.id)
        assert run is not None and run.state != "exited", \
            f"the starter must keep hunting, not exit: {log_text()[-800:]}"
        assert "Traceback" not in log_text(), log_text()[-800:]
    finally:
        await service.stop()


async def test_delivery_starter_unedited_delivers(tmp_path):
    """The delivery starter is the cheat-sheet loop verbatim: unedited it must
    hear a callout, pick a crate up and put +10 on the board."""
    settings = make_settings(tmp_path, mission="delivery")
    service = DroneLifeService(settings)
    await service.start()
    try:
        student, _ = await service.join("Courier-Kid")
        await service.runner.submit_local(student, EXAMPLES_DIR / "template_delivery.py")

        def log_text() -> str:
            return "\n".join(line["line"] for line in
                             service.runner.log_for(student.id).tail(200))

        deadline = time.monotonic() + FLIGHT_BUDGET_S
        await wait_for(deadline, lambda: "got crate" in log_text(), "picked a crate up")
        await wait_for(deadline, lambda: service.engine.score >= 10, "delivered one")
        assert "Traceback" not in log_text(), log_text()[-800:]
    finally:
        await service.stop()
