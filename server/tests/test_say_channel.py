"""dronelife.say() end to end: a real pymavlink STATUSTEXT upstream reaches
the mission's on_text and the reply comes back down the same link."""

import asyncio

from pymavlink import mavutil

from app.api.messages import world_message
from app.service import DroneLifeService
from tests.conftest import Pilot, make_settings


async def test_a_script_can_talk_to_the_siege(tmp_path):
    service = DroneLifeService(make_settings(tmp_path, mission="siege"))
    await service.start()
    try:
        student, _ = await service.join("Talker")
        pilot = await asyncio.to_thread(Pilot, student.port)
        try:
            def check():
                pilot.conn.mav.statustext_send(6, b"wallet")
                assert "wallet 0 coins" in pilot.wait_statustext("wallet")

            await asyncio.to_thread(check)
        finally:
            pilot.close()
        row = next(d for d in world_message(service)["drones"] if d["student_id"] == student.id)
        assert row["pilot"] == {"wallet": 0}, "the wallet rides the drone row"
    finally:
        await service.stop()


async def test_a_mission_without_a_command_surface_ignores_texts(service):
    student, _ = await service.join("Quiet")  # the default mission: delivery
    pilot = await asyncio.to_thread(Pilot, student.port)
    try:
        def check():
            pilot.conn.mav.statustext_send(6, b"wallet")
            pilot.mode_guided()  # something that does answer, to bound the wait
            pilot.wait_ack(mavutil.mavlink.MAV_CMD_DO_SET_MODE)

        await asyncio.to_thread(check)
    finally:
        pilot.close()
    row = next(d for d in world_message(service)["drones"] if d["student_id"] == student.id)
    assert row["pilot"] == {}
