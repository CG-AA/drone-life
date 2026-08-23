"""Canyon: two pre-placed steel walls, no objectives — terrain in the sky.

The smallest possible tile mission: proves the terrain seam (walls exist,
drones crash into their sides and can land on top) with zero building code.
"""

from __future__ import annotations

from .. import hex
from ..mission import Mission, WorldAPI
from ..tiles import TileMap

WALL_E = (-35.0, -23.0)  # two north-south walls -> ~12 m corridor between
WALL_N = (-40.0, 40.0)  # wall extent along north
WALL_HEIGHT = 2  # tiles -> 4 m tall


class CanyonMission(Mission):
    name = "canyon"

    def __init__(self) -> None:
        self.tm = TileMap()

    def setup(self, world: WorldAPI) -> None:
        for e0 in WALL_E:
            for cell in hex.cells_along((WALL_N[0], e0), (WALL_N[1], e0)):
                for _ in range(WALL_HEIGHT):
                    self.tm.place(cell, "steel")
        world.broadcast_text("GAME: canyon walls up, fly low + safe")

    def tile_map(self) -> TileMap:
        return self.tm

    def reset(self, world: WorldAPI) -> None:
        self.tm.clear()
        self.setup(world)
