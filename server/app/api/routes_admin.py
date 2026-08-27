"""Instructor endpoints, guarded by X-Admin-Token."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..runner.manager import RunnerError
from ..service import DroneLifeService
from .auth import err, get_service, require_admin

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


class StudentBody(BaseModel):
    student_id: str


class BotsBody(BaseModel):
    count: int = 5
    script: str = "bot_patrol"
    mode: str = "local"  # "local" (plain subprocess) | "container" (full pipeline)


@router.get("/students")
async def students(service: DroneLifeService = Depends(get_service)) -> dict:
    """Roster for the admin page: who's in, their run state, their link."""
    views = {v.student_id: v for v in service.backend.drones()}
    roster = []
    for s in sorted(service.registry.students.values(), key=lambda s: s.slot):
        run = service.runner.run_for(s.id)
        view = views.get(s.id)
        roster.append({
            "student_id": s.id, "name": s.name, "slot": s.slot, "sysid": s.sysid,
            "run": run.payload() if run else None,
            "connected": bool(view.connected) if view else False,
            "crashed": bool(view.crashed) if view else False,
        })
    return {"students": roster, "score": service.engine.score,
            "mission": service.engine.mission.name, "epoch": service.world.epoch}


@router.post("/reset")
async def reset(service: DroneLifeService = Depends(get_service)) -> dict:
    await service.reset_world()
    return {"ok": True, "epoch": service.world.epoch}


@router.post("/kill")
async def kill(body: StudentBody, service: DroneLifeService = Depends(get_service)) -> dict:
    return {"stopped": await service.runner.stop(body.student_id)}


@router.post("/kick")
async def kick(body: StudentBody, service: DroneLifeService = Depends(get_service)) -> dict:
    if not await service.kick(body.student_id):
        raise err(404, "student", f"no student {body.student_id!r}")
    return {"ok": True}


@router.post("/bots")
async def bots(body: BotsBody, service: DroneLifeService = Depends(get_service)) -> dict:
    if body.mode not in ("local", "container"):
        raise err(400, "mode", "mode must be 'local' or 'container'")
    count = max(1, min(body.count, service.settings.max_students))
    try:
        result = await service.spawn_bots(count, body.script, body.mode)
    except ValueError as exc:
        raise err(400, "script", str(exc)) from exc
    except RunnerError as exc:
        raise err(503, "runner", f"could not start bot containers: {exc}") from exc
    if result["room_full"] and not result["started"]:
        raise err(409, "room_full", "no free slots for bots")
    return result
