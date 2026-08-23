"""Forge: free-form clay building — close a ring of 6 and a furnace lights.

The blueprint-matcher mission: placement is allowed anywhere legal, and
structures are pure data (`ring_blueprint`) plus a few lines of glue.
"""

from __future__ import annotations

from .. import hex
from ..blueprints import BlueprintTracker, ring_blueprint
from ..building import CarrySlots, PlaceTracker, TileSource, tick_sources
from ..hex import Axial
from ..mission import Entity, Mission, WorldAPI
from ..tiles import TileMap

CLAY_PIT_CELL: Axial = (-11, 6)  # infinite clay pile, ~(27, -42)
CLAY_PIT = hex.axial_to_world(CLAY_PIT_CELL)
FURNACE = ring_blueprint("furnace", "clay", radius=1)
PLACE_POINTS = 1
FURNACE_POINTS = 30
ANNOUNCE_EVERY = 20.0


class ForgeMission(Mission):
    name = "forge"

    def __init__(self) -> None:
        self.tm = TileMap()
        self.carry = CarrySlots()
        self.pit = TileSource("clay_pit", *CLAY_PIT, material="clay")
        self.tracker = PlaceTracker(self.tm, self.carry)
        self.blueprints = BlueprintTracker([FURNACE])
        self.furnaces: list[Axial] = []  # lit furnace ring centers
        self.last_announce = 0.0
        self._views = []

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        self.tm.set_keep_out([*world.config.pad_positions(), CLAY_PIT])
        self._announce(world)

    def tile_map(self) -> TileMap:
        return self.tm

    def reset(self, world: WorldAPI) -> None:
        self.tm.clear()
        self.carry.clear()
        self.tracker.reset()
        self.blueprints.reset()
        self.pit.dwell.clear()
        self.furnaces.clear()
        self.last_announce = 0.0
        self.setup(world)

    # ------------------------------------------------------------------ tick

    def _announce(self, world: WorldAPI) -> None:
        world.broadcast_text(
            f"GAME: clay pit at N {round(CLAY_PIT[0])} E {round(CLAY_PIT[1])}")

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = list(world.drones())
        self._views = drones

        for _drone_id, _ in self.carry.sync_losses(drones):
            world.emit_event("tile_lost", "a clay tile was lost")
            world.broadcast_text("GAME: clay lost, grab another")

        for d, _source in tick_sources(drones, [self.pit], self.carry, dt):
            world.emit_event("pickup", f"{d.name} picked up clay", student_id=d.student_id)
            world.send_text(d.id, "GAME: got clay, build a ring of 6")

        placed, refused = self.tracker.tick(drones, dt)
        for p in placed:
            world.add_score(PLACE_POINTS, "clay placed", student_id=p.drone.student_id)
            world.send_text(p.drone.id, "GAME: clay placed +1")
            match = self.blueprints.check(self.tm, p.cell)
            if match is not None:
                self.furnaces.append(match.anchor)
                world.add_score(FURNACE_POINTS, "furnace lit",
                                student_id=p.drone.student_id)
                world.emit_event("furnace_lit", f"{p.drone.name} lit a furnace!",
                                 student_id=p.drone.student_id,
                                 data={"points": FURNACE_POINTS})
                world.broadcast_text(f"GAME: furnace lit! +{FURNACE_POINTS}")
        for d, _cell in refused:
            world.send_text(d.id, "GAME: can't build there")

        if world.now - self.last_announce > ANNOUNCE_EVERY:
            self.last_announce = world.now
            self._announce(world)

    # -------------------------------------------------------------- viewer

    def entities(self) -> list[Entity]:
        out = [self.pit.entity()]
        for i, center in enumerate(self.furnaces):
            n, e = hex.axial_to_world(center)
            out.append(Entity(id=f"furnace{i}", kind="furnace", n=n, e=e, alt=0.0))
        out.extend(self.carry.entities(self._views))
        return out
