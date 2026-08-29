"""Inbound MAVLink dispatch: the student-facing command contract.

Semantics loosely mirror ArduPilot Copter GUIDED mode so skills transfer:
arm requires GUIDED + on-ground, takeoff requires armed, setpoints require
airborne, unsupported commands get COMMAND_ACK UNSUPPORTED, denials always
carry a STATUSTEXT reason. An upstream STATUSTEXT is the one free-text
channel a script has (dronelife.say): it is queued for the mission's
on_text hook, never interpreted here.
"""

from __future__ import annotations

import logging
import math

from pymavlink.dialects.v20 import ardupilotmega as mav2

from ..sim import geo
from ..sim import params as P
from ..sim.drone import DroneSim
from .wire import SEV_WARNING, Link

log = logging.getLogger(__name__)

FORCE_DISARM_MAGIC = 21196  # ArduPilot's param2 for force arm/disarm

_POS_BITS = 0b000000111
_VEL_BITS = 0b000111000
_YAW_IGNORE = 0x400

_LOCAL_FRAMES = {
    mav2.MAV_FRAME_LOCAL_NED,
    mav2.MAV_FRAME_LOCAL_OFFSET_NED,
    mav2.MAV_FRAME_BODY_NED,
    mav2.MAV_FRAME_BODY_OFFSET_NED,
}
_BODY_FRAMES = {mav2.MAV_FRAME_BODY_NED, mav2.MAV_FRAME_BODY_OFFSET_NED}
_GLOBAL_FRAMES = {
    mav2.MAV_FRAME_GLOBAL_INT,
    mav2.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
    mav2.MAV_FRAME_GLOBAL,
    mav2.MAV_FRAME_GLOBAL_RELATIVE_ALT,
}


def handle(link: Link, drone: DroneSim, msg, t: float) -> None:
    typ = msg.get_type()
    if typ in ("HEARTBEAT",):  # liveness is the TCP connection, not heartbeats
        return
    if typ == "COMMAND_LONG":
        _command_long(link, drone, msg, t)
    elif typ == "SET_MODE":  # legacy message some mavutil helpers still emit
        ok, why = drone.set_mode(int(msg.custom_mode), t)
        if not ok:
            link.statustext(why, SEV_WARNING)
    elif typ == "SET_POSITION_TARGET_LOCAL_NED":
        _setpoint_local(link, drone, msg, t)
    elif typ == "SET_POSITION_TARGET_GLOBAL_INT":
        _setpoint_global(link, drone, msg, t)
    elif typ == "STATUSTEXT":  # the script talking back: dronelife.say(...)
        text = msg.text
        drone.hear(text.decode("ascii", "replace") if isinstance(text, bytes) else str(text))
    elif typ.startswith("PARAM_"):
        link.warn_once("param", "params not supported in sim")
    elif typ.startswith("MISSION_"):
        link.warn_once("mission", "missions not supported; use GUIDED")
    elif typ not in link.warned:
        link.warned.add(typ)
        log.info("drone %s: ignoring unsupported message %s", drone.id, typ)


def _ack(link: Link, msg, result: int) -> None:
    link.mav.command_ack_send(
        msg.command, result, 0, 0, msg.get_srcSystem(), msg.get_srcComponent()
    )


def _command_long(link: Link, drone: DroneSim, msg, t: float) -> None:
    cmd = msg.command
    ok, why = False, ""
    if cmd == mav2.MAV_CMD_DO_SET_MODE:
        ok, why = drone.set_mode(int(msg.param2), t)
    elif cmd == mav2.MAV_CMD_COMPONENT_ARM_DISARM:
        force = int(msg.param2) == FORCE_DISARM_MAGIC
        if msg.param1 >= 0.5:
            ok, why = drone.arm(t)
        else:
            ok, why = drone.disarm(force, t)
    elif cmd == mav2.MAV_CMD_NAV_TAKEOFF:
        ok, why = drone.takeoff(float(msg.param7), t)
    elif cmd == mav2.MAV_CMD_NAV_LAND:
        ok, why = drone.set_mode(P.MODE_LAND, t)
    elif cmd == mav2.MAV_CMD_NAV_RETURN_TO_LAUNCH:
        ok, why = drone.set_mode(P.MODE_RTL, t)
    elif cmd == mav2.MAV_CMD_SET_MESSAGE_INTERVAL:
        ok = True  # rates are fixed; accept so tutorial-copied code doesn't stall
    else:
        _ack(link, msg, mav2.MAV_RESULT_UNSUPPORTED)
        return
    _ack(link, msg, mav2.MAV_RESULT_ACCEPTED if ok else mav2.MAV_RESULT_DENIED)
    if not ok and why:
        link.statustext(why, SEV_WARNING)


def _setpoint_warn(link: Link, t: float, why: str) -> None:
    # SET_POSITION_TARGET has no ACK; warn at most every 5 s per connection
    if t - link.last_sp_warn > 5.0:
        link.last_sp_warn = t
        link.statustext(why, SEV_WARNING)


def _apply_setpoint(
    link: Link,
    drone: DroneSim,
    msg,
    t: float,
    pos: tuple[float, float, float],
    vel: tuple[float, float, float],
) -> None:
    mask = msg.type_mask
    use_pos = (mask & _POS_BITS) != _POS_BITS
    use_vel = (mask & _VEL_BITS) != _VEL_BITS
    yaw = float(msg.yaw) if not (mask & _YAW_IGNORE) else None
    if use_pos:
        ok, why = drone.set_pos_target(*pos, yaw, t)
    elif use_vel:
        ok, why = drone.set_vel_target(*vel, yaw, t)
    else:
        ok, why = False, "setpoint had neither position nor velocity bits"
    if not ok:
        _setpoint_warn(link, t, why)


def _setpoint_local(link: Link, drone: DroneSim, msg, t: float) -> None:
    frame = msg.coordinate_frame
    if frame not in _LOCAL_FRAMES:
        link.warn_once(f"frame{frame}", f"frame {frame} not supported")
        return
    x, y, z = float(msg.x), float(msg.y), float(msg.z)
    vx, vy, vz = float(msg.vx), float(msg.vy), float(msg.vz)
    if frame in _BODY_FRAMES:
        # body-relative: rotate by current yaw (x forward, y right)
        c, s = math.cos(drone.yaw), math.sin(drone.yaw)
        x, y = x * c - y * s, x * s + y * c
        vx, vy = vx * c - vy * s, vx * s + vy * c
    if frame == mav2.MAV_FRAME_LOCAL_NED:
        pos = (x, y, z)
    else:  # OFFSET / BODY frames are relative to the current position
        pos = (drone.n + x, drone.e + y, drone.d + z)
    _apply_setpoint(link, drone, msg, t, pos, (vx, vy, vz))


def _setpoint_global(link: Link, drone: DroneSim, msg, t: float) -> None:
    frame = msg.coordinate_frame
    if frame not in _GLOBAL_FRAMES:
        link.warn_once(f"frame{frame}", f"frame {frame} not supported")
        return
    n, e = geo.geo_to_ned(msg.lat_int / 1e7, msg.lon_int / 1e7)
    alt = float(msg.alt)
    if frame in (mav2.MAV_FRAME_GLOBAL_INT, mav2.MAV_FRAME_GLOBAL):
        alt -= geo.ORIGIN_ALT_AMSL  # AMSL -> AGL over our flat arena
    _apply_setpoint(
        link, drone, msg, t, (n, e, -alt), (float(msg.vx), float(msg.vy), float(msg.vz))
    )
