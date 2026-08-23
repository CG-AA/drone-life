"""Gateway + sim through a real blocking mavutil client — the student stack."""

import asyncio

from pymavlink import mavutil

from app.sim import geo

ACCEPTED = mavutil.mavlink.MAV_RESULT_ACCEPTED
DENIED = mavutil.mavlink.MAV_RESULT_DENIED
UNSUPPORTED = mavutil.mavlink.MAV_RESULT_UNSUPPORTED


async def test_heartbeat_encoding(pilot_factory):
    pilot, _ = await pilot_factory("Alice")

    def check():
        msg = pilot.conn.recv_match(type="HEARTBEAT", blocking=True, timeout=10)
        assert msg.type == mavutil.mavlink.MAV_TYPE_QUADROTOR
        assert msg.autopilot == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA
        # mavutil derives flightmode from custom_mode + autopilot: must decode
        assert pilot.conn.flightmode in ("STABILIZE", "GUIDED")

    await asyncio.to_thread(check)


async def test_arm_denied_outside_guided(pilot_factory):
    pilot, _ = await pilot_factory("Bob")

    def check():
        pilot.arm()  # default mode is STABILIZE
        assert pilot.wait_ack(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM) == DENIED
        pilot.wait_statustext("PreArm")

    await asyncio.to_thread(check)


async def test_mode_set_both_paths(pilot_factory):
    pilot, _ = await pilot_factory("Cara")

    def check():
        # modern path: COMMAND_LONG DO_SET_MODE
        pilot.mode_guided()
        assert pilot.wait_ack(mavutil.mavlink.MAV_CMD_DO_SET_MODE) == ACCEPTED
        # legacy path: SET_MODE message (some mavutil helpers still send it)
        pilot.conn.mav.set_mode_send(
            pilot.conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 5)  # LOITER
        deadline = 0
        for _ in range(40):
            hb = pilot.conn.recv_match(type="HEARTBEAT", blocking=True, timeout=10)
            if hb and hb.custom_mode == 5:
                return
            deadline += 1
        raise AssertionError("mode never became LOITER via SET_MODE")

    await asyncio.to_thread(check)


async def test_full_flight_arm_takeoff_goto_land(pilot_factory):
    pilot, student = await pilot_factory("Dave")

    def check():
        pilot.mode_guided()
        pilot.arm()
        pilot.wait_armed_state(True)
        pilot.takeoff(10)
        assert pilot.wait_ack(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF) == ACCEPTED
        pilot.wait_alt(10)
        pilot.goto(20, -15, 10)
        pilot.wait_arrival(20, -15)
        pilot.cmd(mavutil.mavlink.MAV_CMD_NAV_LAND)
        pilot.wait_armed_state(False, timeout=60)  # lands, then auto-disarms
        msg = pilot.pos()
        assert -msg.z < 0.3, "should be on the ground"
        assert abs(msg.x - 20) < 2 and abs(msg.y + 15) < 2, "landed in place"

    await asyncio.to_thread(check)


async def test_velocity_setpoint_times_out(pilot_factory):
    pilot, _ = await pilot_factory("Eve")

    def check():
        pilot.mode_guided()
        pilot.arm()
        pilot.wait_armed_state(True)
        pilot.takeoff(8)
        pilot.wait_alt(8)
        start = pilot.pos()
        pilot.vel(5, 0)  # one setpoint, never refreshed
        pilot.wait_statustext("timed out")
        # after the brake we should have moved north a real distance...
        end = pilot.pos()
        assert 3 < (end.x - start.x) < 40
        # ...and eventually settle into a hover at the hold point
        for _ in range(200):
            end = pilot.pos()
            if abs(end.vx) < 0.3 and abs(end.vy) < 0.3:
                return
        raise AssertionError(f"never settled: vx={end.vx:.2f}")

    await asyncio.to_thread(check)


async def test_bounds_clamp_and_warning(pilot_factory):
    # spawn pads sit at n=-90, 10 m from the south wall: one velocity push hits it
    pilot, _ = await pilot_factory("Finn")

    def check():
        pilot.mode_guided()
        pilot.arm()
        pilot.wait_armed_state(True)
        pilot.takeoff(5)
        pilot.wait_alt(5)
        pilot.vel(-8, 0)
        pilot.wait_statustext("bounds")
        msg = pilot.pos()
        assert msg.x >= -100.01

    await asyncio.to_thread(check)


async def test_unsupported_command_gets_acked(pilot_factory):
    pilot, _ = await pilot_factory("Gita")

    def check():
        pilot.cmd(mavutil.mavlink.MAV_CMD_DO_SET_SERVO, 1, 1500)
        assert pilot.wait_ack(mavutil.mavlink.MAV_CMD_DO_SET_SERVO) == UNSUPPORTED

    await asyncio.to_thread(check)


async def test_global_setpoint_with_fake_origin(pilot_factory):
    pilot, _ = await pilot_factory("Hana")

    def check():
        pilot.mode_guided()
        pilot.arm()
        pilot.wait_armed_state(True)
        pilot.takeoff(10)
        pilot.wait_alt(10)
        lat, lon, _ = geo.ned_to_geo(30, 10, 20)
        pilot.conn.mav.set_position_target_global_int_send(
            0, pilot.conn.target_system, pilot.conn.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, 3576,
            int(lat * 1e7), int(lon * 1e7), 20, 0, 0, 0, 0, 0, 0, 0, 0)
        pilot.wait_arrival(30, 10, tol=1.5)
        pilot.wait_alt(20, tol=1.0)

    await asyncio.to_thread(check)


async def test_disconnect_triggers_rtl_home(pilot_factory, service):
    pilot, student = await pilot_factory("Ivan")

    def fly_out():
        pilot.mode_guided()
        pilot.arm()
        pilot.wait_armed_state(True)
        pilot.takeoff(10)
        pilot.wait_alt(10)
        pilot.goto(0, 0, 10)
        pilot.wait_arrival(0, 0, tol=2.0)

    await asyncio.to_thread(fly_out)
    pilot.close()  # script "dies"

    drone = service.world.drones[service.drone_id_for(student)]
    for _ in range(400):  # grace + RTL + landing, all in racing sim time
        await asyncio.sleep(0.05)
        if drone.on_ground and not drone.armed and abs(drone.n - drone.spawn_n) < 2:
            return
    raise AssertionError(
        f"drone never returned home: n={drone.n:.1f} e={drone.e:.1f} "
        f"alt={drone.alt:.1f} armed={drone.armed} flight={drone.flight}")


def test_severity_constants_match_the_dialect():
    """sim.drone owns the plain ints (pymavlink-free); the wire uses the
    dialect's. mission.py re-exports the sim's. One truth, pinned here."""
    from app.mav import wire
    from app.sim import drone

    assert wire.SEV_INFO == drone.SEV_INFO
    assert wire.SEV_WARNING == drone.SEV_WARNING
