"""dronelife — a thin, readable helper over pymavlink for the drone-life workshop.

Everything here is ordinary pymavlink; read the source to see exactly which
MAVLink messages each helper sends. The workshop guide walks through it.

    from dronelife import connect
    drone = connect()          # uses the DRONE_URL environment variable
    drone.takeoff(10)
    drone.goto(20, 20, 10)     # 20 m north, 20 m east, at 10 m altitude
    drone.land()

Coordinates are meters relative to the arena center: north, east, altitude.
The arena spans -100..100 on both axes; max altitude is 60 m.
"""

from __future__ import annotations

import os
import queue
import threading
import time

from pymavlink import mavutil

# ArduCopter flight mode numbers (same as the real firmware)
GUIDED, LOITER, RTL, LAND, STABILIZE = 4, 5, 6, 9, 0

# SET_POSITION_TARGET type_masks: which fields the drone should use
USE_POSITION_ONLY = 3576  # x, y, z
USE_VELOCITY_ONLY = 3527  # vx, vy, vz


class Drone:
    def __init__(self, url: str, verbose: bool = True) -> None:
        self.verbose = verbose
        self.conn = _connect_with_retry(url)
        self.conn.wait_heartbeat(timeout=15)  # also fills in target_system
        self._say(f"connected to drone (sysid {self.conn.target_system})")

        self._pos = (0.0, 0.0, 0.0)  # (north, east, altitude)
        self._armed = False
        self._mode = 0
        self._game_events: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        # ONE reader thread, ever: mavutil is not thread-safe for reads.
        # Sends happen on the caller's thread; that combination is fine.
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ------------------------------------------------------------ flying

    def takeoff(self, alt: float) -> None:
        """Set GUIDED mode, arm, and climb to `alt` meters."""
        self.set_mode(GUIDED)
        # MAV_CMD_COMPONENT_ARM_DISARM, param1=1 -> arm
        self._cmd(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
        self._wait(lambda: self._armed, 5, "arming (is the drone crashed or mid-air?)")
        self._say("armed")
        # MAV_CMD_NAV_TAKEOFF, param7 = target altitude
        self._cmd(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, p7=alt)
        self._wait(lambda: abs(self.position()[2] - alt) < 0.7, 60, f"climb to {alt} m")
        self._say(f"took off to {alt} m")

    def goto(self, north: float, east: float, alt: float, wait: bool = True,
             tolerance: float = 1.0, timeout: float = 120) -> None:
        """Fly to (north, east) at `alt` meters. Blocks until arrival by default."""
        # SET_POSITION_TARGET_LOCAL_NED: NED means z is DOWN, so z = -alt
        self.conn.mav.set_position_target_local_ned_send(
            0, self.conn.target_system, self.conn.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED, USE_POSITION_ONLY,
            north, east, -alt, 0, 0, 0, 0, 0, 0, 0, 0)
        if wait:
            def arrived() -> bool:
                n, e, a = self.position()
                return abs(n - north) < tolerance and abs(e - east) < tolerance \
                    and abs(a - alt) < tolerance
            self._wait(arrived, timeout, f"goto({north}, {east}, {alt})")

    def move(self, vn: float, ve: float, vup: float, seconds: float) -> None:
        """Fly by velocity (m/s) for a duration. Re-sends the setpoint twice a
        second — the drone brakes to a hover if setpoints stop arriving."""
        end = time.time() + seconds
        while time.time() < end:
            self.conn.mav.set_position_target_local_ned_send(
                0, self.conn.target_system, self.conn.target_component,
                mavutil.mavlink.MAV_FRAME_LOCAL_NED, USE_VELOCITY_ONLY,
                0, 0, 0, vn, ve, -vup, 0, 0, 0, 0, 0)
            time.sleep(0.5)
        n, e, a = self.position()
        self.goto(n, e, a, wait=False)  # crisp stop: hold where we ended up

    def land(self, wait: bool = True) -> None:
        self._cmd(mavutil.mavlink.MAV_CMD_NAV_LAND, 0)
        if wait:
            self._wait(lambda: not self._armed, 90, "landing")
            self._say("landed")

    def rtl(self, wait: bool = True) -> None:
        """Return to your spawn pad and land."""
        self._cmd(mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, 0)
        if wait:
            self._wait(lambda: not self._armed, 180, "returning home")
            self._say("home")

    def set_mode(self, mode: int) -> None:
        self._cmd(mavutil.mavlink.MAV_CMD_DO_SET_MODE,
                  mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, p2=mode)

    # ------------------------------------------------------------ sensing

    def position(self) -> tuple[float, float, float]:
        """(north, east, altitude) in meters, updated 10x per second."""
        return self._pos

    @property
    def armed(self) -> bool:
        return self._armed

    def events(self) -> list[str]:
        """New GAME messages since the last call (crate locations, scores...)."""
        out = []
        while True:
            try:
                out.append(self._game_events.get_nowait())
            except queue.Empty:
                return out

    def next_event(self, timeout: float | None = None) -> str | None:
        """Block until the next GAME message (or timeout)."""
        try:
            return self._game_events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def close(self) -> None:
        self._stop.set()
        self.conn.close()

    # ------------------------------------------------------------ internals

    def _cmd(self, command: int, p1: float, p2: float = 0, p7: float = 0) -> None:
        self.conn.mav.command_long_send(
            self.conn.target_system, self.conn.target_component,
            command, 0, p1, p2, 0, 0, 0, 0, p7)

    def _wait(self, pred, timeout: float, what: str) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return
            time.sleep(0.05)
        raise TimeoutError(f"gave up waiting for: {what}")

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.conn.recv_match(blocking=True, timeout=0.5)
            except Exception:
                break
            if msg is None:
                continue
            t = msg.get_type()
            if t == "LOCAL_POSITION_NED":
                self._pos = (msg.x, msg.y, -msg.z)
            elif t == "HEARTBEAT":
                self._armed = bool(
                    msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self._mode = msg.custom_mode
            elif t == "STATUSTEXT":
                text = msg.text.rstrip("\x00")
                if self.verbose:
                    print(f"DRONE: {text}", flush=True)
                if text.startswith("GAME:"):
                    self._game_events.put(text[5:].strip())

    def _say(self, text: str) -> None:
        if self.verbose:
            print(text, flush=True)


def _connect_with_retry(url: str, tries: int = 5):
    for attempt in range(tries):
        try:
            return mavutil.mavlink_connection(url)
        except (ConnectionRefusedError, OSError):
            if attempt == tries - 1:
                raise
            print(f"drone not answering at {url}, retrying...", flush=True)
            time.sleep(2)


def connect(url: str | None = None, verbose: bool = True) -> Drone:
    """Connect to YOUR drone. The server sets DRONE_URL for you."""
    url = url or os.environ.get("DRONE_URL", "tcp:127.0.0.1:5760")
    return Drone(url, verbose=verbose)
