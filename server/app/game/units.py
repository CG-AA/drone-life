"""Ground units that walk a flow field across the tile map.

The walker's whole contract: follow `FlowField.toward`, climb what is
climbable, chew what is not. No mission knowledge — the caller owns
`tm.remove_top`, re-flooding, scoring, and messaging; units NEVER mutate the
map. Units are mission-owned agents (viewer entities), not sim bodies.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from . import hex
from .hex import Axial
from .path import FlowField
from .tiles import TileMap

_EPS = 1e-9  # dt accumulates in floats; N*dt may land a hair under N*dt exactly


@dataclass
class GroundUnit:
    uid: int
    n: float
    e: float
    speed: float  # m/s along the ground
    heading: float = 0.0  # degrees, 0 = north, clockwise positive east
    alt: float = 0.0  # rides stack tops (refreshed every step)
    chew_cell: Axial | None = None
    chew_acc: float = 0.0
    # stats the owning mission sets per kind; the walker only reads chew_rate
    kind: str = "grunt"
    hp: int = 1
    max_hp: int = 1
    bounty: int = 2  # points for the kill
    keep_cost: int = 1  # hits on the goal when it arrives
    chew_rate: float = 1.0  # x: a 2.0 gnaws through a tile in half the time

    @property
    def cell(self) -> Axial:
        return hex.world_to_axial(self.n, self.e)

    @property
    def chewing(self) -> bool:
        return self.chew_cell is not None


@dataclass
class StepResult:
    arrived: list[GroundUnit] = field(default_factory=list)
    chews: list[tuple[GroundUnit, Axial]] = field(default_factory=list)


def step_units(units: Iterable[GroundUnit], tm: TileMap, flow: FlowField,
               dt: float, chew_s: float,
               chew_factor: Mapping[str, float] | None = None) -> StepResult:
    """Advance every unit one tick. A unit on the goal cell lands in
    `arrived`; otherwise it walks toward the next cell's center, or — when
    that cell is too high to climb — chews it. Marooned on a stack (the next
    cell too far BELOW), it chews its own cell down instead: the pedestal
    rule. A completed chew lands in `chews`; the caller removes the tile and
    re-floods on the version change. `chew_factor` speeds chewing per top
    material (siege: clay goes 3x faster) — unlisted materials chew at 1x."""
    result = StepResult()
    for u in units:
        here = u.cell
        if here == flow.goal:
            result.arrived.append(u)
            continue
        nxt = flow.toward(here)
        if nxt is None:
            continue  # off the field (shouldn't happen in-bounds); hold still
        dh = tm.height(nxt) - tm.height(here)
        if abs(dh) <= flow.climb:
            _walk(u, nxt, tm, dt)
        else:
            target = nxt if dh > 0 else here
            factor = 1.0 if chew_factor is None else chew_factor.get(tm.top(target) or "", 1.0)
            _chew(u, target, dt * factor, chew_s, result)
        u.alt = tm.height_at(u.n, u.e)
    return result


def _walk(u: GroundUnit, nxt: Axial, tm: TileMap, dt: float) -> None:
    u.chew_cell, u.chew_acc = None, 0.0
    tn, te = hex.axial_to_world(nxt, tm.size)
    dn, de = tn - u.n, te - u.e
    dist = math.hypot(dn, de)
    if dist < _EPS:
        return
    u.heading = math.degrees(math.atan2(de, dn))
    step = u.speed * dt
    if dist <= step:
        u.n, u.e = tn, te
    else:
        u.n += dn / dist * step
        u.e += de / dist * step


def _chew(u: GroundUnit, target: Axial, dt: float, chew_s: float,
          result: StepResult) -> None:
    if target != u.chew_cell:
        u.chew_cell, u.chew_acc = target, 0.0  # new target: restart the clock
    u.chew_acc += dt * u.chew_rate
    if u.chew_acc >= chew_s - _EPS:
        u.chew_acc = 0.0
        result.chews.append((u, target))
