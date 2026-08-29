"""Wire-format builders for the viewer feeds (WS frames and their REST mirror).

Pure functions over the service — no I/O, no state. Everything the viewer
learns about the world is shaped here.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..sim import params as P
from ..sim.world import World

if TYPE_CHECKING:
    from ..service import DroneLifeService


def world_message(service: DroneLifeService) -> dict:
    ents = service.engine.entities()
    entities = [
        {"id": e.id, "kind": e.kind, "n": _f(e.n), "e": _f(e.e), "alt": _f(e.alt),
         "data": e.data}
        for e in ents
    ]
    carrying: dict[str, str] = {}
    for ent in ents:
        carrier = ent.data.get("carried_by")
        if isinstance(carrier, str) and carrier:
            carrying[carrier] = ent.id
    drones = []
    for view in sorted(service.backend.drones(), key=lambda v: v.sysid):
        drones.append({
            "id": view.id, "student_id": view.student_id, "name": view.name,
            "sysid": view.sysid, "n": _f(view.n), "e": _f(view.e), "alt": _f(view.alt),
            # velocities let the viewer dead-reckon between 10 Hz frames
            "vn": _f(view.vn), "ve": _f(view.ve), "valt": _f(view.valt),
            "yaw": _f(view.yaw),
            "mode": view.mode, "armed": view.armed, "on_ground": view.on_ground,
            "crashed": view.crashed, "connected": view.connected,
            "carrying": carrying.get(view.id),
        })
    pads = [
        {"slot": s.slot, "n": _f(World.pad_position(s.slot)[0]),
         "e": _f(World.pad_position(s.slot)[1]), "name": s.name}
        for s in service.registry.students.values()
    ]
    return {"epoch": service.world.epoch, "t": round(service.world.t, 2),
            "score": service.engine.score, "drones": drones, "entities": entities,
            "pads": pads, "mission_state": service.engine.hud()}


def hello_message(service: DroneLifeService) -> dict:
    return {
        "proto": 1,
        "arena": {"half": P.ARENA_HALF, "alt_max": P.ALT_MAX,
                  "hex_size": service.hex_size()},
        "mission": service.engine.mission.name,
        "epoch": service.world.epoch,
    }


def tiles_message(service: DroneLifeService) -> dict:
    assert service.tilemap is not None
    return service.tilemap.to_wire()


def _f(x: float) -> float:
    """JSON-safe float: finite, 2 decimals. One NaN must never poison the snapshot."""
    return round(x, 2) if math.isfinite(x) else 0.0
