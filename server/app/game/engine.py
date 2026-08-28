"""Game engine: runs the mission at 10 Hz and owns the services every mission
gets for free — scoring and the event feed. Missions never see sim internals.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Sequence

from ..core.bus import EventBus
from ..sim.backend import DroneBackend, DroneView
from .mission import SEV_INFO, Entity, Mission, MissionConfig

log = logging.getLogger(__name__)

# lifecycle events worth showing the whole class
_FEED_WORTHY = {
    "crashed": "{name} crashed!",
    "respawned": "{name} is back on their pad",
    "orphan_rtl": "{name}'s script ended — drone flying home",
}


class _API:
    """The WorldAPI implementation handed to missions."""

    def __init__(self, engine: GameEngine) -> None:
        self._engine = engine
        self.rng = engine.rng
        self.config = engine.config
        self.now = 0.0
        self._views: Sequence[DroneView] = ()

    def drones(self) -> Sequence[DroneView]:
        return self._views

    def emit_event(self, kind: str, msg: str, student_id: str | None = None,
                   data: dict | None = None) -> None:
        self._engine.bus.emit(kind, msg, student_id=student_id, data=data, t=self.now)

    def add_score(self, points: int, reason: str, student_id: str | None = None,
                  *, feed: bool = True) -> int:
        prev = self._engine.score
        self._engine.score += points
        total = self._engine.score
        if feed:
            self._engine.bus.emit("score", f"{points:+d}: {reason}", student_id=student_id,
                                  data={"points": points, "total": total}, t=self.now)
        # upward century crossings get a celebration line on the projector;
        # a mark re-earned after a dip (siege's keep) celebrates again
        if points > 0 and prev // MILESTONE_EVERY < total // MILESTONE_EVERY:
            mark = total // MILESTONE_EVERY * MILESTONE_EVERY
            self._engine.bus.emit("milestone", f"team passes {mark} points!",
                                  data={"total": total}, t=self.now)
        return total

    def send_text(self, drone_id: str, text: str, severity: int = SEV_INFO) -> None:
        self._engine.backend.send_text(drone_id, text, severity)

    def broadcast_text(self, text: str, severity: int = SEV_INFO) -> None:
        for view in self._views:
            self._engine.backend.send_text(view.id, text, severity)


ERROR_EMIT_EVERY = 30.0  # the feed ring is 200-deep; a 10 Hz bug must not flood it
MILESTONE_EVERY = 100  # team-score marks worth a feed celebration


class GameEngine:
    def __init__(self, backend: DroneBackend, bus: EventBus, mission: Mission,
                 config: MissionConfig, seed: int) -> None:
        self.backend = backend
        self.bus = bus
        self.mission = mission
        self.config = config
        self.rng = random.Random(seed)
        self.score = 0
        self.api = _API(self)
        self._last_error_emit = float("-inf")

    def _mission_error(self, hook: str) -> None:
        """A mission bug must never kill the sim — and must be visible on the
        projector feed, not just in the server log."""
        log.exception("mission.%s failed", hook)
        if self.api.now - self._last_error_emit >= ERROR_EMIT_EVERY:
            self._last_error_emit = self.api.now
            self.bus.emit("mission_error",
                          f"mission bug in {hook}() — check server logs", t=self.api.now)

    def start(self, now: float) -> None:
        self.api.now = now
        self.api._views = self.backend.drones()
        tm = self.mission.tile_map()
        if tm is not None:  # pads are unbuildable in every mission, by default
            tm.protect_pads(self.config.pad_positions())
        try:
            self.mission.setup(self.api)
        except Exception:
            self._mission_error("setup")

    def tick(self, now: float, dt: float, drone_events: list[tuple[DroneView, str]]) -> None:
        self.api.now = now
        self.api._views = self.backend.drones()
        for view, kind in drone_events:
            if kind in _FEED_WORTHY:
                self.bus.emit(kind, _FEED_WORTHY[kind].format(name=view.name),
                              student_id=view.student_id, t=now)
            try:
                self.mission.on_drone_event(self.api, view, kind)
            except Exception:
                self._mission_error("on_drone_event")
        try:
            self.mission.tick(self.api, dt)
        except Exception:
            self._mission_error("tick")

    def entities(self) -> list[Entity]:
        try:
            return self.mission.entities(self.api)
        except Exception:
            self._mission_error("entities")
            return []

    def hud(self) -> dict:
        try:
            return self.mission.hud()
        except Exception:
            self._mission_error("hud")
            return {}

    def reset(self, now: float) -> None:
        self.score = 0
        self.api.now = now
        self.api._views = self.backend.drones()
        try:
            self.mission.reset(self.api)
        except Exception:
            self._mission_error("reset")
        self.bus.emit("reset", "world reset", t=now)
