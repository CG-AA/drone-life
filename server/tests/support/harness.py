"""Mission test harness: drive a mission through the WorldAPI seam — no
MAVLink, no sim. Import as `from tests.support.harness import FakeWorld, view`.

FakeWorld mirrors the real engine `_API` (app/game/engine.py): events are
EventBus-shaped dicts, add_score also lands a "score" event, and run() calls
entities() every tick the way the 10 Hz driver does — so a mission that only
works when tick() ran first fails here too.
"""

from __future__ import annotations

import random

from app.game import hex
from app.game.events import EVENT_KINDS
from app.game.mission import Mission, MissionConfig
from app.sim.backend import DroneView


def view(drone_id="d0", n=0.0, e=0.0, alt=1.0, armed=True, crashed=False) -> DroneView:
    return DroneView(
        id=drone_id, student_id=f"s-{drone_id}", name=drone_id.upper(), sysid=1,
        n=n, e=e, alt=alt, vn=0, ve=0, valt=0, yaw=0, mode="GUIDED",
        armed=armed, on_ground=False, crashed=crashed, connected=True,
    )


def assert_grammar(world: FakeWorld) -> None:
    """The STATUSTEXT law (see mission.py): `GAME: ` prefix, 50 chars max."""
    for _target, text in world.texts:
        assert text.startswith("GAME: "), text
        assert len(text) <= 50, text


class FakeWorld:
    def __init__(self) -> None:
        self.rng = random.Random(1)
        self.config = MissionConfig(arena_half=100, alt_max=60, pads=[hex.pad_cell(0)])
        self.now = 0.0
        self.views: list[DroneView] = []
        self.events: list[dict] = []  # EventBus.emit-shaped records
        self.texts: list[tuple[str, str]] = []  # (target, text); "*" = broadcast
        self.scores: list[tuple[int, str, str | None]] = []
        self.score = 0

    def drones(self):
        return self.views

    def emit_event(self, kind, msg, student_id=None, data=None):
        assert kind in EVENT_KINDS, \
            f"unregistered event kind {kind!r} — add it to app/game/events.py"
        self.events.append({"kind": kind, "msg": msg, "student_id": student_id,
                            "data": data or {}, "t": round(self.now, 2)})

    def add_score(self, points, reason, student_id=None):
        self.score += points
        self.scores.append((points, reason, student_id))
        self.emit_event("score", f"{points:+d}: {reason}", student_id=student_id,
                        data={"points": points, "total": self.score})
        return self.score

    def send_text(self, drone_id, text, severity=6):
        self.texts.append((drone_id, text))

    def broadcast_text(self, text, severity=6):
        self.texts.append(("*", text))

    # --------------------------------------------- engine-shaped drivers

    def start(self, mission: Mission) -> None:
        """Mirror GameEngine.start: pads get protected, then setup() runs with
        the current views visible."""
        tm = mission.tile_map()
        if tm is not None:
            tm.protect_pads(self.config.pad_positions())
        mission.setup(self)

    def drone_event(self, mission: Mission, drone: DroneView, kind: str) -> None:
        """Within a driver step, events are delivered before tick()."""
        mission.on_drone_event(self, drone, kind)

    def run(self, mission, seconds, dt=0.1):
        for _ in range(int(seconds / dt)):
            self.now += dt
            mission.tick(self, dt)
            mission.entities(self)  # the driver serializes after every tick
