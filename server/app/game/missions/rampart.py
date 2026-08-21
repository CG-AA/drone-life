"""Rampart: ferry steel from the quarry and stack it along the ghost wall.

The guided building mission — every mechanic is a building.py primitive; this
file is constants, one `allowed` rule, and GAME texts.
"""

from __future__ import annotations

from .. import hex
from ..building import (
    CarrySlots,
    PlaceTracker,
    TileSource,
    fmt_cell,
    hover_alt_hint,
    tick_sources,
)
from ..mission import Entity, Mission, WorldAPI
from ..tiles import TileMap

QUARRY = (-30.0, 40.0)  # infinite steel pile
WALL_FROM, WALL_TO = (10.0, -60.0), (10.0, -10.0)  # ghost wall endpoints (world m)
WALL_HEIGHT = 2  # tiles per cell -> a 4 m wall
PLACE_POINTS = 2
WALL_BONUS = 40
ANNOUNCE_EVERY = 15.0


class RampartMission(Mission):
    name = "rampart"

    def __init__(self) -> None:
        self.tm = TileMap()
        self.carry = CarrySlots()
        self.quarry = TileSource("quarry", *QUARRY, material="steel")
        self.targets = hex.cells_along(WALL_FROM, WALL_TO)
        target_set = set(self.targets)
        self.tracker = PlaceTracker(
            self.tm, self.carry,
            allowed=lambda c: c in target_set and self.tm.height(c) < WALL_HEIGHT)
        self.total = len(self.targets) * WALL_HEIGHT
        self.done = False
        self.last_announce = 0.0
        self._views = []

    # ------------------------------------------------------------- lifecycle

    def setup(self, world: WorldAPI) -> None:
        self.tm.set_keep_out([*world.config.pads, QUARRY])
        self._announce(world)

    def tile_map(self) -> TileMap:
        return self.tm

    def reset(self, world: WorldAPI) -> None:
        self.tm.clear()
        self.carry.clear()
        self.tracker.reset()
        self.quarry.dwell.clear()
        self.done = False
        self.last_announce = 0.0
        self.setup(world)

    # ------------------------------------------------------------------ tick

    def built(self) -> int:
        return sum(self.tm.height(c) for c in self.targets)

    def _announce(self, world: WorldAPI) -> None:
        world.broadcast_text(f"GAME: quarry at N {round(QUARRY[0])} E {round(QUARRY[1])}")
        gap = next((c for c in self.targets if self.tm.height(c) < WALL_HEIGHT), None)
        if gap is not None:
            world.broadcast_text(
                f"GAME: wall gap at {fmt_cell(gap)} hover {hover_alt_hint(self.tm, gap)}")

    def tick(self, world: WorldAPI, dt: float) -> None:
        drones = list(world.drones())
        self._views = drones

        for _drone_id, _ in self.carry.sync_losses(drones):
            world.emit_event("tile_lost", "a steel tile was lost")
            world.broadcast_text("GAME: steel lost, grab another")

        for d, _source in tick_sources(drones, [self.quarry], self.carry, dt):
            world.emit_event("pickup", f"{d.name} picked up steel", student_id=d.student_id)
            world.send_text(d.id, "GAME: got steel, place on the wall")

        placed, refused = self.tracker.tick(drones, dt)
        for p in placed:
            total = world.add_score(PLACE_POINTS, f"wall tile at {fmt_cell(p.cell)}",
                                    student_id=p.drone.student_id)
            world.emit_event("tile_placed", f"{p.drone.name} built the wall",
                             student_id=p.drone.student_id)
            world.send_text(p.drone.id,
                            f"GAME: placed! wall {self.built()}/{self.total} +{PLACE_POINTS}")
            if self.built() >= self.total and not self.done:
                self.done = True
                world.add_score(WALL_BONUS, "rampart complete",
                                student_id=p.drone.student_id)
                world.emit_event("wall_complete", f"the rampart stands! +{WALL_BONUS}",
                                 data={"points": WALL_BONUS, "team": total + WALL_BONUS})
                world.broadcast_text(f"GAME: rampart complete! +{WALL_BONUS}")
        for d, _cell in refused:
            world.send_text(d.id, "GAME: not a wall cell")

        if not self.done and world.now - self.last_announce > ANNOUNCE_EVERY:
            self.last_announce = world.now
            self._announce(world)

    # -------------------------------------------------------------- viewer

    def entities(self) -> list[Entity]:
        out = [self.quarry.entity()]
        for cell in self.targets:
            have = self.tm.height(cell)
            if have >= WALL_HEIGHT:
                continue
            n, e = hex.axial_to_world(cell)
            out.append(Entity(id=f"ghost_{cell[0]}_{cell[1]}", kind="ghost_tile",
                              n=n, e=e, alt=self.tm.top_alt(cell),
                              data={"material": "steel", "need": WALL_HEIGHT,
                                    "have": have, "size": hex.HEX_SIZE}))
        out.extend(self.carry.entities(self._views))
        return out
