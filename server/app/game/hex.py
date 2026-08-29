"""Axial hex grid math over the NED ground plane. Pure functions, no deps.

Pointy-top hexes with axial coordinates (q, r):
    e = size * sqrt(3) * (q + r / 2)
    n = size * 3/2 * r
All six neighbor centers sit sqrt(3) * size apart. This module is the single
server-side source of truth for hex geometry — the viewer learns `size` from
the tiles message, never from a duplicated constant.
"""

from __future__ import annotations

import math

Axial = tuple[int, int]  # (q, r)

HEX_SIZE = 3.0  # m, center-to-corner. 5.2 m pitch: fair for goto(tolerance=1.0)

SQRT3 = math.sqrt(3.0)

# axial direction ring, counter-clockwise starting east
DIRECTIONS: tuple[Axial, ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

# Spawn pads: rows of adjacent cells along the south edge (r = -20 is
# n = -90 at HEX_SIZE 3). Pads are cells, never free meters, so every pad
# marker fills exactly one lattice hex. A row of 20 spans e = -52..47; slot
# 20 starts the next row one cell north (n = -85.5), and so on — a room of
# 64 is four rows, all inside the arena.
PAD_ROW_R = -20
PAD_Q0 = 0
PADS_PER_ROW = 20


def axial_to_world(cell: Axial, size: float = HEX_SIZE) -> tuple[float, float]:
    """Cell -> (n, e) center in meters."""
    q, r = cell
    return size * 1.5 * r, size * SQRT3 * (q + r / 2.0)


def world_to_axial(n: float, e: float, size: float = HEX_SIZE) -> Axial:
    """(n, e) in meters -> the cell containing it."""
    rf = (2.0 / 3.0) * n / size
    qf = (SQRT3 / 3.0) * e / size - rf / 2.0
    return axial_round(qf, rf)


def axial_round(qf: float, rf: float) -> Axial:
    """Cube rounding: snap fractional axial coords to the nearest cell."""
    x, z = qf, rf
    y = -x - z
    rx, ry, rz = round(x), round(y), round(z)
    dx, dy, dz = abs(rx - x), abs(ry - y), abs(rz - z)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy <= dz:
        rz = -rx - ry
    return int(rx), int(rz)


def pad_cell(slot: int) -> Axial:
    row, col = divmod(slot, PADS_PER_ROW)
    # each row north sits half a pitch further east; pull q back every other
    # row so every row starts at the same edge
    return PAD_Q0 + col - (row + 1) // 2, PAD_ROW_R + row


def pad_position(slot: int) -> tuple[float, float]:
    """Pad center in meters: where a drone spawns and flies home to."""
    return axial_to_world(pad_cell(slot))


def add(a: Axial, b: Axial) -> Axial:
    return a[0] + b[0], a[1] + b[1]


def sub(a: Axial, b: Axial) -> Axial:
    return a[0] - b[0], a[1] - b[1]


def distance(a: Axial, b: Axial) -> int:
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def neighbors(cell: Axial) -> list[Axial]:
    return [add(cell, d) for d in DIRECTIONS]


def ring(center: Axial, radius: int) -> list[Axial]:
    """The cells exactly `radius` steps from center; ring(c, 1) is 6 cells."""
    if radius <= 0:
        return [center]
    out: list[Axial] = []
    cell = add(center, (DIRECTIONS[4][0] * radius, DIRECTIONS[4][1] * radius))
    for direction in DIRECTIONS:
        for _ in range(radius):
            out.append(cell)
            cell = add(cell, direction)
    return out


def disc(center: Axial, radius: int) -> list[Axial]:
    """All cells within `radius` steps; disc(c, 2) is 19 cells."""
    out: list[Axial] = []
    for dq in range(-radius, radius + 1):
        for dr in range(max(-radius, -dq - radius), min(radius, -dq + radius) + 1):
            out.append((center[0] + dq, center[1] + dr))
    return out


def line(a: Axial, b: Axial) -> list[Axial]:
    """Cells along the straight segment from a to b, endpoints included."""
    steps = distance(a, b)
    if steps == 0:
        return [a]
    out: list[Axial] = []
    for i in range(steps + 1):
        f = i / steps
        # nudge off exact cell-edge midpoints so rounding is stable
        qf = a[0] + (b[0] - a[0]) * f + 1e-6
        rf = a[1] + (b[1] - a[1]) * f + 1e-6
        cell = axial_round(qf, rf)
        if not out or out[-1] != cell:
            out.append(cell)
    return out


def cells_along(a: tuple[float, float], b: tuple[float, float],
                size: float = HEX_SIZE) -> list[Axial]:
    """Cells the straight WORLD segment (n, e) -> (n, e) passes through.

    Unlike line(), which connects two cells in axial space and may drift off
    the world segment by up to a cell, this hugs the segment itself — the
    right tool for walls at real coordinates. The result is edge-connected.
    """
    (n0, e0), (n1, e1) = a, b
    steps = max(1, math.ceil(math.hypot(n1 - n0, e1 - e0) / (size * 0.75)))
    out: list[Axial] = []
    for i in range(steps + 1):
        f = i / steps
        cell = world_to_axial(n0 + (n1 - n0) * f, e0 + (e1 - e0) * f, size)
        if not out or out[-1] != cell:
            out.append(cell)
    return out


def rotate60(cell: Axial, times: int = 1) -> Axial:
    """Rotate about the origin by 60 degrees, `times` steps counter-clockwise."""
    q, r = cell
    for _ in range(times % 6):
        q, r = -r, q + r
    return q, r
