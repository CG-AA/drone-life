"""The same first flight as template.py, in raw pymavlink.

This is exactly what dronelife.py does under the hood — and exactly how you
would talk to a real ArduPilot drone.
"""

import os

from pymavlink import mavutil

GUIDED = 4  # ArduCopter mode number, same as the real firmware

conn = mavutil.mavlink_connection(os.environ["DRONE_URL"])
conn.wait_heartbeat(timeout=15)
print(f"connected: sysid={conn.target_system}")


def command(cmd, p1=0, p2=0, p7=0):
    conn.mav.command_long_send(conn.target_system, conn.target_component,
                               cmd, 0, p1, p2, 0, 0, 0, 0, p7)


def pump():
    """Drain incoming messages; print what the drone tells us."""
    while (m := conn.recv_match(type="STATUSTEXT", blocking=False)) is not None:
        print("DRONE:", m.text.rstrip("\x00"))


def position():
    msg = conn.recv_match(type="LOCAL_POSITION_NED", blocking=True, timeout=5)
    return (msg.x, msg.y, -msg.z) if msg else (0.0, 0.0, 0.0)


# 1. GUIDED mode, then arm
command(mavutil.mavlink.MAV_CMD_DO_SET_MODE,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, GUIDED)
command(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
conn.motors_armed_wait()
print("armed")

# 2. take off to 10 m and wait until we get there
command(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, p7=10)
while abs(position()[2] - 10) > 0.7:
    pump()

# 3. fly to (north=20, east=20) at 10 m — type_mask 3576 = use position only
conn.mav.set_position_target_local_ned_send(
    0, conn.target_system, conn.target_component,
    mavutil.mavlink.MAV_FRAME_LOCAL_NED, 3576,
    20, 20, -10, 0, 0, 0, 0, 0, 0, 0, 0)
while True:
    n, e, alt = position()
    pump()
    if abs(n - 20) < 1 and abs(e - 20) < 1:
        break

print("made it — landing")
command(mavutil.mavlink.MAV_CMD_NAV_LAND)
while conn.motors_armed():
    conn.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
print("done")
