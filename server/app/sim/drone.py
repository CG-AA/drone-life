"""Single-drone kinematic sim: ArduPilot-GUIDED-flavored mode machine over a point mass.

Position/velocity live in NED (x north, y east, z down; altitude = -z). Position
targets are approached on a braking parabola (v = sqrt(2*a*dist), capped), which
gives smooth trapezoidal motion with no overshoot and nothing to tune.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from . import params as P
from .terrain import FLAT, Terrain

SEV_INFO = 6  # MAV_SEVERITY_INFO
SEV_WARNING = 4  # MAV_SEVERITY_WARNING


class Flight(Enum):
    IDLE = "idle"  # on ground
    TAKEOFF = "takeoff"
    FLY = "fly"  # airborne: position hold / goto / velocity
    LAND = "land"
    RTL_CLIMB = "rtl_climb"
    RTL_CRUISE = "rtl_cruise"
    CRASHED = "crashed"


def _brake_speed(dist: float, a: float, vmax: float) -> float:
    return min(vmax, math.sqrt(max(0.0, 2.0 * a * dist)))


@dataclass
class DroneSim:
    id: str
    student_id: str
    name: str
    sysid: int
    spawn_n: float
    spawn_e: float

    n: float = 0.0
    e: float = 0.0
    d: float = 0.0  # down; altitude = -d
    vn: float = 0.0
    ve: float = 0.0
    vd: float = 0.0
    yaw: float = 0.0

    mode: int = P.MODE_STABILIZE
    armed: bool = False
    flight: Flight = Flight.IDLE
    connected: bool = False

    # targets
    tn: float = 0.0
    te: float = 0.0
    td: float = 0.0
    vel_sp: tuple[float, float, float] | None = None
    vel_sp_time: float = 0.0
    target_yaw: float | None = None

    disarm_at: float | None = None
    crash_until: float | None = None
    last_bounds_warn: float = -1e9
    ground_d: float = 0.0  # d of the surface under the drone (-terrain height)

    outbox: list[tuple[int, str]] = field(default_factory=list)  # (severity, text)
    events: list[str] = field(default_factory=list)  # lifecycle events for the engine

    def __post_init__(self) -> None:
        self.n = self.spawn_n
        self.e = self.spawn_e

    # ------------------------------------------------------------------ helpers

    @property
    def alt(self) -> float:
        return -self.d

    @property
    def on_ground(self) -> bool:
        if self.flight == Flight.IDLE:
            return True
        return self.flight == Flight.CRASHED and self.d >= self.ground_d - 0.01

    @property
    def crashed(self) -> bool:
        return self.flight == Flight.CRASHED

    @property
    def mode_name(self) -> str:
        return P.MODE_NAMES.get(self.mode, str(self.mode))

    def say(self, text: str, severity: int = SEV_INFO) -> None:
        self.outbox.append((severity, text[:50]))

    def _hold_here(self) -> None:
        self.tn, self.te, self.td = self.n, self.e, self.d
        self.vel_sp = None

    # ------------------------------------------------------------- command API
    # All return (ok, reason) so the gateway can ACK/DENY with a STATUSTEXT.

    def set_mode(self, mode: int, t: float) -> tuple[bool, str]:
        if mode not in P.MODE_NAMES:
            return False, f"mode {mode} not supported in sim"
        if mode == P.MODE_STABILIZE and not self.on_ground:
            return False, "STABILIZE only on the ground here"
        self.mode = mode
        if mode in (P.MODE_GUIDED, P.MODE_LOITER):
            if not self.on_ground and self.flight != Flight.CRASHED:
                self.flight = Flight.FLY
                self._hold_here()
        elif mode == P.MODE_RTL:
            if self.armed and not self.on_ground:
                self._start_rtl(t)
        elif mode == P.MODE_LAND and self.armed and not self.on_ground:
            self.flight = Flight.LAND
            self.tn, self.te = self.n, self.e
            self.vel_sp = None
        return True, ""

    def arm(self, t: float) -> tuple[bool, str]:
        if self.armed:
            return True, ""
        if self.flight == Flight.CRASHED:
            return False, "PreArm: crashed, wait for respawn"
        if self.mode != P.MODE_GUIDED:
            return False, "PreArm: set mode GUIDED first"
        if not self.on_ground:
            return False, "PreArm: not landed"
        self.armed = True
        self.disarm_at = None
        self.events.append("armed")
        return True, ""

    def disarm(self, force: bool, t: float) -> tuple[bool, str]:
        if not self.armed:
            return True, ""
        if self.on_ground:
            self.armed = False
            self.disarm_at = None
            self.events.append("disarmed")
            return True, ""
        if force:
            self.crash(t, "force disarmed mid-air")
            return True, ""
        return False, "disarm denied: not landed (force=21196)"

    def takeoff(self, alt: float, t: float) -> tuple[bool, str]:
        if self.mode != P.MODE_GUIDED:
            return False, "takeoff needs GUIDED"
        if not self.armed:
            return False, "takeoff needs arming first"
        if not self.on_ground or self.flight == Flight.CRASHED:
            return False, "already flying"
        # from atop a stack, always climb clear of the roof
        alt = min(max(alt, -self.ground_d + 0.5), P.ALT_MAX)
        self.tn, self.te, self.td = self.n, self.e, -alt
        self.vel_sp = None
        self.disarm_at = None
        self.flight = Flight.TAKEOFF
        self.events.append("takeoff")
        return True, ""

    def set_pos_target(
        self, n: float, e: float, d: float, yaw: float | None, t: float
    ) -> tuple[bool, str]:
        ok, why = self._can_accept_setpoint()
        if not ok:
            return False, why
        self.tn = min(max(n, -P.ARENA_HALF), P.ARENA_HALF)
        self.te = min(max(e, -P.ARENA_HALF), P.ARENA_HALF)
        self.td = min(max(d, -P.ALT_MAX), -0.5)
        self.vel_sp = None
        self.target_yaw = yaw
        self.flight = Flight.FLY
        return True, ""

    def set_vel_target(
        self, vn: float, ve: float, vd: float, yaw: float | None, t: float
    ) -> tuple[bool, str]:
        ok, why = self._can_accept_setpoint()
        if not ok:
            return False, why
        self.vel_sp = (vn, ve, vd)
        self.vel_sp_time = t
        self.target_yaw = yaw
        self.flight = Flight.FLY
        return True, ""

    def _can_accept_setpoint(self) -> tuple[bool, str]:
        if self.mode != P.MODE_GUIDED:
            return False, "setpoint ignored: not in GUIDED"
        if not self.armed:
            return False, "setpoint ignored: not armed"
        if self.on_ground:
            return False, "setpoint ignored: take off first"
        return True, ""

    def crash(self, t: float, why: str) -> None:
        self.armed = False
        self.vel_sp = None
        self.flight = Flight.CRASHED
        self.crash_until = None  # set at ground contact
        self.events.append("crashed")
        self.say(f"CRASH: {why}", SEV_WARNING)

    def reset_to_pad(self) -> None:
        """Teleport home, disarmed. Used by world reset and self-service reset."""
        self.n, self.e, self.d = self.spawn_n, self.spawn_e, 0.0
        self.vn = self.ve = self.vd = 0.0
        self.yaw = 0.0
        self.mode = P.MODE_STABILIZE
        self.armed = False
        self.flight = Flight.IDLE
        self.vel_sp = None
        self.disarm_at = None
        self.crash_until = None
        self.ground_d = 0.0  # pads are keep-out for tiles, always flat

    def _start_rtl(self, t: float) -> None:
        self.vel_sp = None
        self.tn, self.te = self.n, self.e
        self.td = min(self.d, -P.RTL_ALT)  # climb to RTL_ALT unless already higher
        self.flight = Flight.RTL_CLIMB

    # ---------------------------------------------------------------- stepping

    def step(self, t: float, dt: float, terrain: Terrain = FLAT) -> None:
        self.ground_d = -terrain.height_at(self.n, self.e)

        if self.flight == Flight.IDLE:
            if self.armed and self.disarm_at is not None and t >= self.disarm_at:
                self.armed = False
                self.disarm_at = None
                self.events.append("disarmed")
            return

        if self.flight == Flight.CRASHED:
            self._step_crashed(t, dt)
            return

        pn, pe, pd = self.n, self.e, self.d
        des_vn, des_ve, des_vd = self._desired_velocity(t)

        # accel-limit horizontal as a vector, vertical separately
        dvn, dve = des_vn - self.vn, des_ve - self.ve
        dmag = math.hypot(dvn, dve)
        max_dv = P.A_XY_MAX * dt
        if dmag > max_dv:
            dvn, dve = dvn / dmag * max_dv, dve / dmag * max_dv
        self.vn += dvn
        self.ve += dve
        dvd = des_vd - self.vd
        max_dvd = P.A_Z_MAX * dt
        self.vd += min(max(dvd, -max_dvd), max_dvd)

        self.n += self.vn * dt
        self.e += self.ve * dt
        self.d += self.vd * dt

        self._clamp_bounds(t)
        self._check_terrain(t, pn, pe, pd, terrain)
        self.ground_d = -terrain.height_at(self.n, self.e)
        self._step_yaw(dt)
        self._check_transitions(t)

    def _desired_velocity(self, t: float) -> tuple[float, float, float]:
        if self.flight == Flight.FLY and self.vel_sp is not None:
            if t - self.vel_sp_time > P.VEL_SP_TIMEOUT:
                self._hold_here()
                self.say("velocity setpoint timed out: holding", SEV_WARNING)
            else:
                vn, ve, vd = self.vel_sp
                mag = math.hypot(vn, ve)
                if mag > P.V_XY_MAX:
                    vn, ve = vn / mag * P.V_XY_MAX, ve / mag * P.V_XY_MAX
                vd = min(max(vd, -P.V_UP_MAX), P.V_DOWN_MAX)
                return vn, ve, vd

        if self.flight == Flight.LAND:
            speed = P.V_DOWN_FINAL if self.alt < P.FINAL_ALT else P.V_DOWN_MAX
            hn, he = self._horiz_toward(self.tn, self.te)
            return hn, he, speed

        # everything else approaches (tn, te, td) on the braking parabola
        hn, he = self._horiz_toward(self.tn, self.te)
        dz = self.td - self.d
        cap = P.V_UP_MAX if dz < 0 else P.V_DOWN_MAX
        vd = math.copysign(_brake_speed(abs(dz), P.A_Z_MAX, cap), dz) if abs(dz) > 1e-3 else 0.0
        if self.flight in (Flight.TAKEOFF, Flight.RTL_CLIMB) and self.alt < P.FINAL_ALT and dz > 0:
            vd = min(vd, P.V_DOWN_FINAL)
        return hn, he, vd

    def _horiz_toward(self, tn: float, te: float) -> tuple[float, float]:
        dn, de = tn - self.n, te - self.e
        dist = math.hypot(dn, de)
        if dist < 1e-3:
            return 0.0, 0.0
        speed = _brake_speed(dist, P.A_XY_MAX, P.V_XY_MAX)
        return dn / dist * speed, de / dist * speed

    def _step_crashed(self, t: float, dt: float) -> None:
        if self.d < self.ground_d:  # still falling (wrecks rest on rooftops too)
            self.vd = P.CRASH_FALL_SPEED
            self.d = min(self.ground_d, self.d + self.vd * dt)
            if self.d >= self.ground_d:
                self.d = self.ground_d
                self.vn = self.ve = self.vd = 0.0
                self.crash_until = t + P.CRASH_DOWN_TIME
        elif self.crash_until is None:
            self.crash_until = t + P.CRASH_DOWN_TIME
        elif t >= self.crash_until:
            self.reset_to_pad()
            self.events.append("respawned")
            self.say("respawned on your pad", SEV_INFO)

    def _clamp_bounds(self, t: float) -> None:
        clamped = False
        if abs(self.n) > P.ARENA_HALF:
            self.n = math.copysign(P.ARENA_HALF, self.n)
            self.vn = 0.0
            clamped = True
        if abs(self.e) > P.ARENA_HALF:
            self.e = math.copysign(P.ARENA_HALF, self.e)
            self.ve = 0.0
            clamped = True
        if self.d < -P.ALT_MAX:
            self.d = -P.ALT_MAX
            self.vd = 0.0
            clamped = True
        if self.d > 0.0 and self.flight not in (Flight.LAND, Flight.CRASHED):
            self.d = 0.0
            self.vd = 0.0
        if clamped and t - self.last_bounds_warn > P.BOUNDS_WARN_INTERVAL:
            self.last_bounds_warn = t
            self.say("bounds: clamped at arena edge", SEV_WARNING)

    def _check_terrain(self, t: float, pn: float, pe: float, pd: float,
                       terrain: Terrain) -> None:
        """Swept collision against the terrain along this tick's motion.

        Entering a column from the side crashes; descending onto one from above
        rides its roof (the same soft semantics as the flat-ground clamp).
        """
        if self.flight in (Flight.IDLE, Flight.CRASHED):
            return
        seg_n, seg_e, seg_d = self.n - pn, self.e - pe, self.d - pd
        k = max(1, math.ceil(math.hypot(seg_n, seg_e) / P.TERRAIN_SWEEP_STEP))
        start_alt = -pd
        clamp_alt: float | None = None
        for i in range(1, k + 1):
            f = i / k
            sn, se = pn + seg_n * f, pe + seg_e * f
            s_alt = -(pd + seg_d * f)
            if clamp_alt is not None:
                s_alt = max(s_alt, clamp_alt)
            h = terrain.height_at(sn, se)
            if s_alt >= h - 1e-6:
                continue
            if start_alt >= h - 1e-6:  # came from at-or-above: ride the roof
                clamp_alt = h if clamp_alt is None else max(clamp_alt, h)
            else:  # flew into the side: rewind to the last clear sample
                fb = (i - 1) / k
                self.n, self.e = pn + seg_n * fb, pe + seg_e * fb
                self.d = pd + seg_d * fb
                self.vn = self.ve = 0.0
                self.crash(t, "hit a wall")
                return
        if clamp_alt is not None and self.alt < clamp_alt:
            self.d = -clamp_alt
            self.vd = 0.0

    def _step_yaw(self, dt: float) -> None:
        if self.target_yaw is not None:
            want = self.target_yaw
        elif math.hypot(self.vn, self.ve) > 0.5:
            want = math.atan2(self.ve, self.vn)
        else:
            return
        err = (want - self.yaw + math.pi) % (2 * math.pi) - math.pi
        step = min(max(err, -P.YAW_RATE_MAX * dt), P.YAW_RATE_MAX * dt)
        self.yaw = (self.yaw + step + math.pi) % (2 * math.pi) - math.pi

    def _check_transitions(self, t: float) -> None:
        if self.flight == Flight.TAKEOFF:
            if abs(self.d - self.td) < P.ARRIVE_RADIUS:
                self.flight = Flight.FLY
        elif self.flight == Flight.RTL_CLIMB:
            if abs(self.d - self.td) < P.ARRIVE_RADIUS:
                self.tn, self.te = self.spawn_n, self.spawn_e
                self.flight = Flight.RTL_CRUISE
        elif self.flight == Flight.RTL_CRUISE:
            if math.hypot(self.tn - self.n, self.te - self.e) < P.ARRIVE_RADIUS:
                self.flight = Flight.LAND
        elif self.flight == Flight.LAND and self.d >= self.ground_d - 1e-6:
            self.d = self.ground_d
            self.vn = self.ve = self.vd = 0.0
            self.flight = Flight.IDLE
            self.disarm_at = t + P.DISARM_DELAY
            self.events.append("landed")
