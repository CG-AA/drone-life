"""Outbound telemetry, driven from the 20 Hz sim tick.

Rates: LOCAL_POSITION_NED + ATTITUDE 10 Hz, GLOBAL_POSITION_INT 5 Hz,
HEARTBEAT + SYS_STATUS 1 Hz, STATUSTEXT whenever queued. If a connection's
write buffer backs up we skip its telemetry for the tick but never drop
ACKs or STATUSTEXTs (those are sent from the handler/outbox paths).
"""

from __future__ import annotations

import math

from pymavlink.dialects.v20 import ardupilotmega as mav2

from ..sim import geo
from ..sim import params as P
from ..sim.drone import DroneSim
from .wire import Link

MAX_BUFFER = 64 * 1024


def send_heartbeat(link: Link, drone: DroneSim) -> None:
    base_mode = mav2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED | mav2.MAV_MODE_FLAG_GUIDED_ENABLED
    if drone.armed:
        base_mode |= mav2.MAV_MODE_FLAG_SAFETY_ARMED
    link.mav.heartbeat_send(
        mav2.MAV_TYPE_QUADROTOR,
        mav2.MAV_AUTOPILOT_ARDUPILOTMEGA,  # makes mavutil.mode_mapping() work
        base_mode,
        drone.mode,  # ArduCopter custom_mode number
        mav2.MAV_STATE_ACTIVE if drone.armed else mav2.MAV_STATE_STANDBY,
    )


def send_tick(link: Link, drone: DroneSim, t: float, tick: int) -> None:
    """Called every sim tick (20 Hz) per connected drone."""
    # STATUSTEXTs queued by the sim/game go out immediately, always
    while drone.outbox:
        severity, text = drone.outbox.pop(0)
        link.statustext(text, severity)

    if link.buffered > MAX_BUFFER:
        return  # stalled client: shed telemetry, keep the connection alive

    ms = int(t * 1000) & 0xFFFFFFFF
    if tick % 2 == 0:  # 10 Hz
        link.mav.local_position_ned_send(
            ms, drone.n, drone.e, drone.d, drone.vn, drone.ve, drone.vd)
        hspeed = math.hypot(drone.vn, drone.ve)
        link.mav.attitude_send(ms, 0.0, -0.03 * hspeed, drone.yaw, 0.0, 0.0, 0.0)
    if tick % 4 == 0:  # 5 Hz
        lat, lon, amsl = geo.ned_to_geo(drone.n, drone.e, drone.alt)
        hdg = int(math.degrees(drone.yaw) % 360 * 100)
        link.mav.global_position_int_send(
            ms, int(lat * 1e7), int(lon * 1e7), int(amsl * 1000), int(drone.alt * 1000),
            int(drone.vn * 100), int(drone.ve * 100), int(drone.vd * 100), hdg,
        )
    if tick % P.TICK_HZ == 0:  # 1 Hz
        send_heartbeat(link, drone)
        link.mav.sys_status_send(0, 0, 0, 200, 12600, -1, 100, 0, 0, 0, 0, 0, 0)
