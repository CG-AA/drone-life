"""The mission plugin contract — v1's stable extensibility seam.

A mission sees the world ONLY through WorldAPI and describes itself to the
viewer ONLY through Entity records. New game content = a new Mission subclass
registered in missions/__init__.py; physics, networking, and rendering stay
untouched.

GAME text grammar (STATUSTEXT is 50 chars and students regex it — keep this
law so a parser written for one mission transfers to the next): positions are
announced as "<thing> at N <int> E <int>"; confirmations end with "!".
"""

from __future__ import annotations

import random
from abc import ABC
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol

from ..sim.backend import DroneView
from . import hex
from .hex import Axial

if TYPE_CHECKING:
    from .tiles import TileMap

# one truth for severities: the sim owns them; the MAVLink dialect constants in
# mav/wire.py are pinned equal by test
from ..sim.drone import SEV_INFO, SEV_WARNING  # noqa: F401  (mission authors' import surface)


def fmt_world(n: float, e: float) -> str:
    """Position in the announce grammar: 'N 10 E -55' (see module docstring)."""
    return f"N {round(n)} E {round(e)}"

# every kind on_drone_event can receive; producers: the sim (armed…respawned),
# the gateway (connected/disconnected/orphan_rtl), the service (joined)
DRONE_EVENT_KINDS: tuple[str, ...] = (
    "joined", "connected", "disconnected", "armed", "disarmed",
    "takeoff", "landed", "crashed", "respawned", "orphan_rtl",
)


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
    pads: list[Axial]  # cells, so a pad can never sit off the lattice

    def pad_positions(self) -> list[tuple[float, float]]:
        return [hex.axial_to_world(c) for c in self.pads]


class WorldAPI(Protocol):
    """Everything a mission may do. Provided by the game engine."""

    rng: random.Random
    config: MissionConfig
    now: float  # sim seconds

    @property
    def score(self) -> int:
        """The team total — read it for summaries; add_score is how it moves."""
        ...

    def drones(self) -> Sequence[DroneView]: ...
    def emit_event(self, kind: str, msg: str, student_id: str | None = None,
                   data: dict | None = None) -> None: ...
    def add_score(self, points: int, reason: str, student_id: str | None = None,
                  *, feed: bool = True) -> int:
        """Add to the team total and return it. `feed=True` posts a '+N: reason'
        row on the projector; pass feed=False when the mission emits its own,
        richer event for the same action (one row per thing that happened),
        or for high-frequency scoring (tower shots) that would drown the feed.
        Milestones fire either way."""
        ...
    def send_text(self, drone_id: str, text: str, severity: int = SEV_INFO) -> None: ...
    def broadcast_text(self, text: str, severity: int = SEV_INFO) -> None: ...


class Mission(ABC):  # noqa: B024 — every hook is optional by design
    name: ClassVar[str] = "base"

    def setup(self, world: WorldAPI) -> None:  # noqa: B027 — optional hook
        pass

    def tick(self, world: WorldAPI, dt: float) -> None:  # noqa: B027
        """Called at 10 Hz."""

    def on_drone_event(self, world: WorldAPI, drone: DroneView, kind: str) -> None:  # noqa: B027
        """kind is one of DRONE_EVENT_KINDS; delivered before tick() each step."""

    def entities(self, world: WorldAPI) -> list[Entity]:
        """Called at 10 Hz after tick() — and on WS connect, possibly before
        the first tick — so read live state from `world`, don't stash it."""
        return []

    def hud(self) -> dict:
        """What the projector's status strip shows for this mission — a small
        JSON-serializable dict (integers, short strings) rebuilt from live
        state on every frame and on WS connect, possibly before the first
        tick. Empty by default: missions with nothing to count show nothing.
        Siege: wave, state, countdown, keep hp; delivery: crates, delivered."""
        return {}

    def tile_map(self) -> TileMap | None:
        """Missions with terrain return their TileMap; the service wires it
        into the sim as Terrain and broadcasts it to viewers. Identity must be
        stable for the process lifetime — reset() clears and rebuilds the same
        map, never replaces it."""
        return None

    def reset(self, world: WorldAPI) -> None:  # noqa: B027
        pass
