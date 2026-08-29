"""Blueprints: relative hex patterns that become structures when tiles
complete them.

Matching is anchored at the just-placed cell (never scans the map) and is
rotation-invariant: all 6 orientations via hex.rotate60. A new structure is a
Blueprint literal plus a few lines of mission glue — never new matching code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from . import hex
from .hex import Axial
from .tiles import TileMap


@dataclass(frozen=True)
class Requirement:
    dq: int
    dr: int
    material: str
    height: int = 1  # satisfied iff the cell stacks at least this high
    max_height: int | None = None  # …and no higher than this (a beacon is a line of singles)


@dataclass(frozen=True)
class Blueprint:
    name: str
    reqs: tuple[Requirement, ...]


@dataclass(frozen=True)
class Match:
    blueprint: str
    anchor: Axial  # world cell where the pattern origin landed
    cells: tuple[Axial, ...]  # absolute matched cells


def ring_blueprint(name: str, material: str, radius: int = 1,
                   height: int = 1) -> Blueprint:
    """A ring of one material around an (unconstrained) center."""
    reqs = tuple(Requirement(q, r, material, height)
                 for q, r in hex.ring((0, 0), radius))
    return Blueprint(name, reqs)


def match_at(tm: TileMap, bp: Blueprint, anchor: Axial, rotation: int = 0) -> Match | None:
    cells = []
    for req in bp.reqs:
        cell = hex.add(anchor, hex.rotate60((req.dq, req.dr), rotation))
        if tm.height(cell) < req.height or tm.top(cell) != req.material:
            return None
        if req.max_height is not None and tm.height(cell) > req.max_height:
            return None
        cells.append(cell)
    return Match(bp.name, anchor, tuple(cells))


def find_match(tm: TileMap, bp: Blueprint, placed: Axial,
               claimed: frozenset[Axial] = frozenset()) -> Match | None:
    """First complete, unclaimed match that includes the just-placed cell.

    Cost ~ 6 rotations x |reqs|^2 lookups per placement — placements are rare.
    """
    for rotation in range(6):
        for req in bp.reqs:
            offset = hex.rotate60((req.dq, req.dr), rotation)
            anchor = hex.sub(placed, offset)
            match = match_at(tm, bp, anchor, rotation)
            if match is not None and not set(match.cells) & claimed:
                return match
    return None


def pre_place(tm: TileMap, bp: Blueprint, anchor: Axial) -> list[Axial]:
    """Mission-setup helper: build the blueprint outright. Returns its cells."""
    cells = []
    for req in bp.reqs:
        cell = hex.add(anchor, (req.dq, req.dr))
        for _ in range(req.height):
            tm.place(cell, req.material)
        cells.append(cell)
    return cells


class BlueprintTracker:
    """Glue missions shouldn't rewrite: dedup of already-built structures."""

    def __init__(self, blueprints: Sequence[Blueprint]) -> None:
        self.blueprints = list(blueprints)
        self.claimed: set[Axial] = set()

    def check(self, tm: TileMap, placed: Axial,
              extra_claimed: frozenset[Axial] = frozenset()) -> Match | None:
        """`extra_claimed`: cells another tracker owns (siege runs several —
        a tile that is part of one structure must not complete another)."""
        for bp in self.blueprints:
            match = find_match(tm, bp, placed, frozenset(self.claimed) | extra_claimed)
            if match is not None:
                self.claimed.update(match.cells)
                return match
        return None

    def reset(self) -> None:
        self.claimed.clear()
