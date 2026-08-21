"""The drone-backend seam.

Everything above the sim (game engine, API, WS) talks to DroneBackend and reads
DroneView snapshots. The kinematic sim + MAVLink gateway are the v1
implementation; a future ArduPilot-SITL adapter would implement the same
interface out-of-process (SITL brings its own MAVLink endpoint, so the gateway
lives *inside* the backend, not above it).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from .drone import DroneSim


@dataclass(frozen=True)
class DroneView:
    """Read-only snapshot handed to missions and the WS serializer."""

    id: str
    student_id: str
    name: str
    sysid: int
    n: float
    e: float
    alt: float
    vn: float
    ve: float
    valt: float
    yaw: float
    mode: str
    armed: bool
    on_ground: bool
    crashed: bool
    connected: bool

    @classmethod
    def of(cls, d: DroneSim) -> DroneView:
        return cls(
            id=d.id, student_id=d.student_id, name=d.name, sysid=d.sysid,
            n=d.n, e=d.e, alt=d.alt, vn=d.vn, ve=d.ve, valt=-d.vd, yaw=d.yaw,
            mode=d.mode_name, armed=d.armed, on_ground=d.on_ground,
            crashed=d.crashed, connected=d.connected,
        )


class DroneBackend(ABC):
    @abstractmethod
    async def spawn(self, drone_id: str, student_id: str, name: str, slot: int) -> DroneView: ...

    @abstractmethod
    async def remove(self, drone_id: str) -> None: ...

    @abstractmethod
    def drones(self) -> Sequence[DroneView]: ...

    @abstractmethod
    def send_text(self, drone_id: str, text: str, severity: int) -> None: ...
