"""TileMap: hex cells -> material stacks.

Doubles as the sim's Terrain (structural match for sim.terrain.Terrain — no sim
behavior imported) and as the pathability oracle for future ground units. Knows
nothing about drones, dwells, or scoring: that lives one layer up in
building.py, which is what makes height_at safe to hand to the sim.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

from ..sim.params import ARENA_HALF
from . import hex
from .hex import Axial

TILE_HEIGHT = 2.0  # m of world altitude per stacked tile
MAX_STACK = 4  # 8 m < RTL_ALT=15: drones flying home always clear walls
VALID_MATERIALS = frozenset({"steel", "clay"})  # new material: one string here + a viewer color
KEEPOUT_RADIUS = 6.0  # m around pads/dropoffs: unbuildable


class TileMap:
    def __init__(self, size: float = hex.HEX_SIZE) -> None:
        self.size = size
        self.version = 0  # bumped on every mutation; the service broadcasts on change
        self._stacks: dict[Axial, list[str]] = {}
        self._keep_out: list[tuple[float, float]] = []
        self._keep_out_radius = KEEPOUT_RADIUS
        self._pad_keep_out: list[tuple[float, float]] = []

    # ------------------------------------------------------------ configuration

    def set_keep_out(self, points: Iterable[tuple[float, float]],
                     radius: float = KEEPOUT_RADIUS) -> None:
        """Mark circles (mission landmarks: quarries, dropoffs, gates) whose
        cells reject placement. Spawn pads need no entry here — the engine
        protects them via protect_pads()."""
        self._keep_out = list(points)
        self._keep_out_radius = radius

    def protect_pads(self, points: Iterable[tuple[float, float]]) -> None:
        """Engine-owned: every spawn pad is unbuildable, always. Kept separate
        from set_keep_out so no mission can forget it or clear it."""
        self._pad_keep_out = list(points)

    # --------------------------------------------------------------- placement
    # (ok, reason) command-API style, like DroneSim, so callers can message it.

    def can_place(self, cell: Axial, material: str) -> tuple[bool, str]:
        if material not in VALID_MATERIALS:
            return False, f"unknown material {material!r}"
        if not self.in_bounds(cell):
            return False, "outside the arena"
        n, e = hex.axial_to_world(cell, self.size)
        for kn, ke in self._pad_keep_out:
            if math.hypot(n - kn, e - ke) <= KEEPOUT_RADIUS:
                return False, "too close to a pad"
        for kn, ke in self._keep_out:
            if math.hypot(n - kn, e - ke) <= self._keep_out_radius:
                return False, "keep-out zone"
        if self.height(cell) >= MAX_STACK:
            return False, "stack is full"
        return True, ""

    def place(self, cell: Axial, material: str) -> tuple[bool, str]:
        ok, why = self.can_place(cell, material)
        if not ok:
            return False, why
        self._stacks.setdefault(cell, []).append(material)
        self.version += 1
        return True, ""

    def remove_top(self, cell: Axial) -> str | None:
        stack = self._stacks.get(cell)
        if not stack:
            return None
        material = stack.pop()
        if not stack:
            del self._stacks[cell]
        self.version += 1
        return material

    def clear(self) -> None:
        self._stacks.clear()
        self.version += 1

    # ----------------------------------------------------------------- queries

    def stack(self, cell: Axial) -> tuple[str, ...]:
        return tuple(self._stacks.get(cell, ()))

    def top(self, cell: Axial) -> str | None:
        stack = self._stacks.get(cell)
        return stack[-1] if stack else None

    def height(self, cell: Axial) -> int:
        return len(self._stacks.get(cell, ()))

    def top_alt(self, cell: Axial) -> float:
        return self.height(cell) * TILE_HEIGHT

    def cells(self) -> Iterator[tuple[Axial, tuple[str, ...]]]:
        for cell, stack in self._stacks.items():
            yield cell, tuple(stack)

    def in_bounds(self, cell: Axial) -> bool:
        n, e = hex.axial_to_world(cell, self.size)
        limit = ARENA_HALF - self.size  # whole hex inside, corners included
        return abs(n) <= limit and abs(e) <= limit

    # ------------------------------------------------- sim Terrain (structural)

    def height_at(self, n: float, e: float) -> float:
        return self.top_alt(hex.world_to_axial(n, e, self.size))

    # ------------------------------------- pathability for future ground units

    def blocked(self, cell: Axial) -> bool:
        return self.height(cell) > 0

    def passable_neighbors(self, cell: Axial, climb: int = 0) -> list[Axial]:
        """In-bounds neighbors a ground unit could walk to, climbing at most
        `climb` tiles up or down per step."""
        here = self.height(cell)
        return [nb for nb in hex.neighbors(cell)
                if self.in_bounds(nb) and abs(self.height(nb) - here) <= climb]

    # -------------------------------------------------------------------- wire

    def to_wire(self) -> dict:
        return {
            "geometry": {"size": self.size, "tile_height": TILE_HEIGHT},
            "cells": [{"q": q, "r": r, "stack": list(stack)}
                      for (q, r), stack in sorted(self._stacks.items())],
        }
