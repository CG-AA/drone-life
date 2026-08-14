"""The mission plugin contract — v1's stable extensibility seam.

A mission sees the world ONLY through WorldAPI and describes itself to the
viewer ONLY through Entity records. New game content = a new Mission subclass
registered in missions/__init__.py; physics, networking, and rendering stay
untouched.
"""

from __future__ import annotations

import random
from abc import ABC
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from ..sim.backend import DroneView

SEV_INFO = 6
SEV_WARNING = 4


@dataclass(frozen=True)
class Entity:
    """Serialized verbatim to the viewer each frame; rendered by `kind`."""

    id: str
    kind: str  # "crate" | "dropoff" | future kinds
    n: float
    e: float
    alt: float
    data: dict = field(default_factory=dict)


@dataclass
class MissionConfig:
    arena_half: float
    alt_max: float
    pads: list[tuple[float, float]]
    dropoff: tuple[float, float] = (0.0, 0.0)


class WorldAPI(Protocol):
    """Everything a mission may do. Provided by the game engine."""

    rng: random.Random
    config: MissionConfig
    now: float  # sim seconds

    def drones(self) -> Sequence[DroneView]: ...
    def emit_event(self, kind: str, msg: str, student_id: str | None = None,
                   data: dict | None = None) -> None: ...
    def add_score(self, points: int, reason: str, student_id: str | None = None) -> int: ...
    def send_text(self, drone_id: str, text: str, severity: int = SEV_INFO) -> None: ...
    def broadcast_text(self, text: str, severity: int = SEV_INFO) -> None: ...


class Mission(ABC):  # noqa: B024 — every hook is optional by design
    name: ClassVar[str] = "base"

    def setup(self, world: WorldAPI) -> None:  # noqa: B027 — optional hook
        pass

    def tick(self, world: WorldAPI, dt: float) -> None:  # noqa: B027
        """Called at 10 Hz."""

    def on_drone_event(self, world: WorldAPI, drone: DroneView, kind: str) -> None:  # noqa: B027
        """kind: joined|connected|disconnected|armed|disarmed|takeoff|landed|
        crashed|respawned|orphan_rtl"""

    def entities(self) -> list[Entity]:
        return []

    def reset(self, world: WorldAPI) -> None:  # noqa: B027
        pass
