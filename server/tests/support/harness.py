"""Mission test harness: drive a mission through the WorldAPI seam — no
MAVLink, no sim. Import as `from tests.support.harness import FakeWorld, view`.

FakeWorld mirrors the real engine `_API` (app/game/engine.py): events are
EventBus-shaped dicts, add_score also lands a "score" event, and run() calls
entities() every tick the way the 10 Hz driver does — so a mission that only
works when tick() ran first fails here too.
"""

from __future__ import annotations

import random
import re

from app.game import hex
from app.game.engine import milestone_crossed
from app.game.events import EVENT_KINDS
from app.game.mission import Mission, MissionConfig
from app.sim.backend import DroneView


def view(drone_id="d0", n=0.0, e=0.0, alt=1.0, armed=True, crashed=False) -> DroneView:
    return DroneView(
        id=drone_id, student_id=f"s-{drone_id}", name=drone_id.upper(), sysid=1,
        n=n, e=e, alt=alt, vn=0, ve=0, valt=0, yaw=0, mode="GUIDED",
        armed=armed, on_ground=False, crashed=crashed, connected=True,
    )


_POS_RE = re.compile(r" at N -?\d+ E -?\d+($|[ ,!])")


def check_text(text: str) -> None:
    """The STATUSTEXT law (see mission.py), checked on every emission.

    Prefix and length are hard rules (the sim truncates to 50 chars silently —
    an over-long text reaches students cut off mid-word). Positions must come
    from fmt_world/fmt_cell: bots regex `at N <int> E <int>` (bot_courier.py),
    so a hand-rolled coordinate format breaks them silently. Floats never
    belong in GAME text. The "confirmations end with !" clause stays a style
    rule — mid-sentence `!` is legitimate ("tower up! +15"), so it can't be
    mechanized.
    """
    assert text.startswith("GAME: "), text
    assert len(text) <= 50, f"statustext would truncate: {text!r} ({len(text)})"
    if " at N" in text:
        assert _POS_RE.search(text), f"malformed position (use fmt_world): {text!r}"
    assert not re.search(r"\d\.\d", text), f"float leaked into GAME text: {text!r}"


def assert_grammar(world: FakeWorld) -> None:
    """Re-check every text a mission produced (kept for explicit callers;
    FakeWorld already checks each emission as it happens)."""
    for _target, text in world.texts:
        check_text(text)


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

    def add_score(self, points, reason, student_id=None, *, feed=True):
        prev = self.score
        self.score += points
        self.scores.append((points, reason, student_id))
        if feed:
            self.emit_event("score", f"{points:+d}: {reason}", student_id=student_id,
                            data={"points": points, "total": self.score})
        mark = milestone_crossed(prev, points, self.score)
        if mark is not None:
            self.emit_event("milestone", f"team passes {mark} points!",
                            data={"total": self.score})
        return self.score

    def send_text(self, drone_id, text, severity=6):
        check_text(text)
        self.texts.append((drone_id, text))

    def broadcast_text(self, text, severity=6):
        check_text(text)
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
