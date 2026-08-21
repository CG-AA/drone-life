"""Terrain seam: the single question the sim asks the game about the ground.

The sim never knows about tiles, hexes, or missions — only "how high is the
ground at (n, e)?". game/tiles.py satisfies this Protocol structurally; FLAT
reproduces the pre-terrain world bit-for-bit and is the default everywhere.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Terrain(Protocol):
    def height_at(self, n: float, e: float) -> float:
        """Ground height in meters at (n, e). Always >= 0."""
        ...


class _Flat:
    def height_at(self, n: float, e: float) -> float:
        return 0.0


FLAT: Terrain = _Flat()
