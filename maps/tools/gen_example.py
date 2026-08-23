#!/usr/bin/env python3
"""Generate maps/example.tmj + maps/tiles.png — a 200 m arena with terrain,
districts, a no-fly tower and authored pads. Pure Python (zlib PNG writer), so
it runs anywhere:   python3 maps/tools/gen_example.py

The result is a normal Tiled map: open it in Tiled to edit, save, done.
"""

from __future__ import annotations

import json
import math
import random
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from app.game import hex  # noqa: E402  (pads must land on the server's lattice)

OUT = Path(__file__).resolve().parents[1]
W = H = 40  # tiles
TW, TH = 64, 32  # px, 2:1
MPT = 5.0  # metres per tile -> ±100 m
ALT_MAX = 60
HALF = W * MPT / 2

# tile ids (0-based in the sheet; gid = id + 1)
GRASS, GRASS2, WATER, SAND, ROAD, DARK = range(6)
COLORS = {
    GRASS: [(74, 128, 68), (82, 140, 74), (68, 118, 62)],
    GRASS2: [(80, 136, 72), (90, 150, 80), (74, 128, 68)],
    WATER: [(46, 92, 150), (54, 104, 168), (40, 82, 138)],
    SAND: [(196, 176, 122), (206, 188, 134), (186, 166, 112)],
    ROAD: [(84, 86, 92), (92, 94, 100), (76, 78, 84)],
    DARK: [(52, 96, 56), (58, 106, 62), (46, 86, 50)],
}


# ------------------------------------------------------------------ png writer

def write_png(path: Path, width: int, height: int, rgba: bytearray) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


TREE_W, TREE_H = 32, 48


def make_trees(path: Path) -> None:
    """One 32x48 tree: trunk + three-tone canopy, transparent elsewhere."""
    rng = random.Random(11)
    img = bytearray(TREE_W * TREE_H * 4)
    def put(x, y, c):
        if 0 <= x < TREE_W and 0 <= y < TREE_H:
            i = (y * TREE_W + x) * 4
            img[i:i + 4] = bytes([*c, 255])
    for y in range(TREE_H - 14, TREE_H - 2):
        for x in range(TREE_W // 2 - 2, TREE_W // 2 + 2):
            put(x, y, (96, 66, 38))
    for cx, cy, r, c in [(16, 22, 11, (44, 122, 62)), (11, 26, 8, (36, 104, 52)), (21, 25, 8, (58, 146, 78))]:
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    put(x, y, c if rng.random() > 0.15 else (30, 90, 46))
    for x in range(TREE_W // 2 - 8, TREE_W // 2 + 8):
        for y in range(TREE_H - 3, TREE_H):
            if abs(x - TREE_W // 2) + abs(y - (TREE_H - 2)) * 3 < 8:
                put(x, y, (20, 40, 30))
    write_png(path, TREE_W, TREE_H, img)


def make_tiles(path: Path) -> None:
    rng = random.Random(7)
    n = len(COLORS)
    img = bytearray(TW * n * TH * 4)
    for tid, palette in COLORS.items():
        for y in range(TH):
            for x in range(TW):
                # inside the 2:1 diamond?
                dx = abs(x + 0.5 - TW / 2) / (TW / 2)
                dy = abs(y + 0.5 - TH / 2) / (TH / 2)
                if dx + dy > 1.0:
                    continue
                edge = dx + dy > 0.93
                c = palette[2] if edge else palette[rng.randrange(2) if rng.random() < 0.35 else 0]
                if tid == WATER and (x // 4 + y // 2) % 5 == 0 and rng.random() < 0.5:
                    c = palette[1]
                i = ((y * TW * n) + tid * TW + x) * 4
                img[i:i + 4] = bytes([*c, 255])
    write_png(path, TW * n, TH, img)


# ------------------------------------------------------------------ terrain

def tile_to_ned(tx: float, ty: float) -> tuple[float, float]:
    return HALF - tx * MPT, HALF - ty * MPT


def ned_to_px(n: float, e: float) -> tuple[float, float]:
    """NED → Tiled iso object pixels (tile-height units on both axes)."""
    tx = (HALF - n) / MPT
    ty = (HALF - e) / MPT
    return tx * TH, ty * TH


def terrain(rng: random.Random) -> list[int]:
    data = []
    for ty in range(H):
        for tx in range(W):
            n, e = tile_to_ned(tx + 0.5, ty + 0.5)
            d_lake = math.hypot(n - 55, e + 55)
            if d_lake < 28:
                tid = WATER
            elif d_lake < 36:
                tid = SAND
            elif abs(n) < 2.6 or abs(e) < 2.6:
                tid = ROAD  # two avenues through the dropoff
            elif -30 <= n <= 30 and 10 <= e <= 70 and (int(n + 100) % 20 < 5 or int(e + 100) % 20 < 5):
                tid = ROAD  # downtown grid
            elif -30 <= n <= 30 and 10 <= e <= 70:
                tid = DARK
            else:
                tid = GRASS if rng.random() < 0.7 else GRASS2
            data.append(tid + 1)
    return data


def obj_rect(oid: int, name: str, cls: str, n0: float, e0: float, n1: float, e1: float,
             props: dict | None = None) -> dict:
    """Axis-aligned NED rectangle → Tiled polygon (px)."""
    corners = [(n1, e1), (n0, e1), (n0, e0), (n1, e0)]  # NE, SE, SW, NW in NED terms
    px = [ned_to_px(n, e) for n, e in corners]
    ox, oy = px[0]
    return {"id": oid, "name": name, "class": cls, "x": ox, "y": oy, "width": 0, "height": 0,
            "rotation": 0, "visible": True,
            "polygon": [{"x": x - ox, "y": y - oy} for x, y in px],
            "properties": [{"name": k, "type": "string" if isinstance(v, str) else
                            "bool" if isinstance(v, bool) else "int", "value": v}
                           for k, v in (props or {}).items()]}


def obj_point(oid: int, name: str, cls: str, n: float, e: float, props: dict | None = None) -> dict:
    x, y = ned_to_px(n, e)
    return {"id": oid, "name": name, "class": cls, "point": True, "x": x, "y": y, "width": 0,
            "height": 0, "rotation": 0, "visible": True,
            "properties": [{"name": k, "type": "int", "value": v} for k, v in (props or {}).items()]}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    make_tiles(OUT / "tiles.png")
    make_trees(OUT / "trees.png")
    rng = random.Random(3)
    oid = 1
    regions = []
    for name, cls, box, props in [
        ("harbor", "district", (20, -90, 90, -20), {"label": "Harbor"}),
        ("downtown", "district", (-30, 10, 30, 70), {"label": "Downtown", "speed_limit": 5}),
        ("tower", "no_fly", (-72, 38, -48, 62), {"label": "Radio tower", "no_spawn": True}),
    ]:
        regions.append(obj_rect(oid, name, cls, *box, props))
        oid += 1
    pads = []
    for slot in range(20):  # the server's default row: adjacent lattice cells, r = -20
        n, e = hex.pad_position(slot)
        pads.append(obj_point(oid, f"pad{slot}", "pad", n, e, {"slot": slot}))
        oid += 1
    points = [obj_point(oid, "dropoff", "", 0, 0)]
    oid += 1
    # a few trees along the harbor shore and the south-east grass (props layer:
    # tile objects, drawn by the viewer, ignored by the server)
    props_tree = []
    for n, e in [(30, -30), (14, -84), (86, -14), (-40, -60), (-60, -30), (-80, 20),
                 (60, 60), (75, 30), (-20, 85), (40, 88)]:
        x, y = ned_to_px(n, e)
        props_tree.append({"id": oid, "name": "", "class": "", "gid": len(COLORS) + 1,
                           "x": x, "y": y, "width": TREE_W, "height": TREE_H, "rotation": 0,
                           "visible": True})
        oid += 1
    tmap = {
        "type": "map", "version": "1.10", "tiledversion": "1.10.2",
        "orientation": "isometric", "renderorder": "right-down", "infinite": False,
        "width": W, "height": H, "tilewidth": TW, "tileheight": TH,
        "compressionlevel": -1, "nextlayerid": 6, "nextobjectid": oid,
        "properties": [
            {"name": "meters_per_tile", "type": "float", "value": MPT},
            {"name": "alt_max", "type": "float", "value": ALT_MAX},
        ],
        "tilesets": [{
            "firstgid": 1, "name": "tiles", "tilewidth": TW, "tileheight": TH,
            "tilecount": len(COLORS), "columns": len(COLORS), "image": "tiles.png",
            "imagewidth": TW * len(COLORS), "imageheight": TH, "margin": 0, "spacing": 0,
        }, {
            "firstgid": len(COLORS) + 1, "name": "trees", "tilewidth": TREE_W,
            "tileheight": TREE_H, "tilecount": 1, "columns": 1, "image": "trees.png",
            "imagewidth": TREE_W, "imageheight": TREE_H, "margin": 0, "spacing": 0,
        }],
        "layers": [
            {"id": 1, "type": "tilelayer", "name": "ground", "visible": True, "opacity": 1,
             "x": 0, "y": 0, "width": W, "height": H, "data": terrain(rng)},
            {"id": 2, "type": "objectgroup", "name": "regions", "visible": True, "opacity": 1,
             "x": 0, "y": 0, "draworder": "topdown", "objects": regions},
            {"id": 3, "type": "objectgroup", "name": "pads", "visible": True, "opacity": 1,
             "x": 0, "y": 0, "draworder": "topdown", "objects": pads},
            {"id": 4, "type": "objectgroup", "name": "points", "visible": True, "opacity": 1,
             "x": 0, "y": 0, "draworder": "topdown", "objects": points},
            {"id": 5, "type": "objectgroup", "name": "props", "visible": True, "opacity": 1,
             "x": 0, "y": 0, "draworder": "topdown", "objects": props_tree},
        ],
    }
    (OUT / "example.tmj").write_text(json.dumps(tmap, separators=(",", ":")) + "\n")
    print(f"wrote {OUT / 'example.tmj'}, {OUT / 'tiles.png'}, {OUT / 'trees.png'}")


if __name__ == "__main__":
    main()
