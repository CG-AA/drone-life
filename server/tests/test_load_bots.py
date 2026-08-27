"""Load smoke: N local bots in real time for 60 s. Tick overruns must stay
under 1% and world broadcasts at >= 9 Hz.   Run with:  make load

Defaults to 10 bots; rehearse the real class with `make load LOAD_BOTS=20`
on the machine that will run the workshop — a laptop and the lab server do
not have the same headroom.
"""

import asyncio
import os

import pytest

from app.service import DroneLifeService
from tests.conftest import find_port_base, make_settings

pytestmark = pytest.mark.load

BOTS = int(os.environ.get("LOAD_BOTS", "10"))
SLOTS = BOTS + 2


class CountingHub:
    def __init__(self) -> None:
        self.worlds = 0

    def broadcast_world(self, data: dict) -> None:
        self.worlds += 1

    def broadcast_tiles(self, data: dict) -> None:
        pass  # tile missions broadcast these; without it the driver would raise

    def send_run_state(self, student_id: str, payload: dict) -> None:
        pass


async def test_a_full_class_of_bots_for_a_minute(tmp_path):
    settings = make_settings(
        tmp_path,
        sim_unthrottled=False,
        mavlink_base_port=find_port_base(SLOTS),
        max_students=SLOTS,
        sim_seed=3,
    )
    service = DroneLifeService(settings)
    hub = CountingHub()
    service.hub = hub
    await service.start()
    try:
        await service.spawn_bots(BOTS, "bot_patrol", "local")
        await asyncio.sleep(10)  # let everyone connect and take off
        airborne = sum(1 for v in service.backend.drones() if not v.on_ground)
        assert airborne >= BOTS - 2, f"only {airborne}/{BOTS} bots got airborne"

        ticks0, over0, worlds0 = service.ticks, service.overruns, hub.worlds
        await asyncio.sleep(60)
        ticks = service.ticks - ticks0
        overruns = service.overruns - over0
        world_hz = (hub.worlds - worlds0) / 60

        assert ticks >= 1100, f"tick starvation: {ticks} ticks in 60s"
        assert overruns / max(ticks, 1) < 0.01, f"{overruns} overruns in {ticks} ticks"
        assert world_hz >= 9, f"world broadcast at {world_hz:.1f} Hz"
        assert service.driver_errors == 0, f"{service.driver_errors} driver errors under load"
    finally:
        await service.stop()
