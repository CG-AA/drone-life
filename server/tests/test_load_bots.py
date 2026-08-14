"""Load smoke: 10 local bots in real time for 60 s. Tick overruns must stay
under 1% and world broadcasts at >= 9 Hz.   Run with:  make load
"""

import asyncio

import pytest

from app.service import DroneLifeService
from tests.conftest import find_port_base, make_settings

pytestmark = pytest.mark.load


class CountingHub:
    def __init__(self) -> None:
        self.worlds = 0

    def broadcast_world(self, data: dict) -> None:
        self.worlds += 1

    def send_run_state(self, student_id: str, payload: dict) -> None:
        pass


async def test_ten_bots_for_a_minute(tmp_path):
    settings = make_settings(
        tmp_path,
        sim_unthrottled=False,
        mavlink_base_port=find_port_base(12),
        max_students=12,
        sim_seed=3,
    )
    service = DroneLifeService(settings)
    hub = CountingHub()
    service.hub = hub
    await service.start()
    try:
        await service.spawn_bots(10, "bot_patrol", "local")
        await asyncio.sleep(10)  # let everyone connect and take off
        airborne = sum(1 for v in service.backend.drones() if not v.on_ground)
        assert airborne >= 8, f"only {airborne}/10 bots got airborne"

        ticks0, over0, worlds0 = service.ticks, service.overruns, hub.worlds
        await asyncio.sleep(60)
        ticks = service.ticks - ticks0
        overruns = service.overruns - over0
        world_hz = (hub.worlds - worlds0) / 60

        assert ticks >= 1100, f"tick starvation: {ticks} ticks in 60s"
        assert overruns / max(ticks, 1) < 0.01, f"{overruns} overruns in {ticks} ticks"
        assert world_hz >= 9, f"world broadcast at {world_hz:.1f} Hz"
    finally:
        await service.stop()
