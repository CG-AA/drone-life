"""Instructor endpoints, guarded by X-Admin-Token."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..service import DroneLifeService
from .auth import err, get_service, require_admin

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


class StudentBody(BaseModel):
    student_id: str


class BotsBody(BaseModel):
    count: int = 5
    script: str = "bot_patrol"
    mode: str = "local"  # "local" (plain subprocess) | "container" (full pipeline)


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
        started = await service.spawn_bots(count, body.script, body.mode)
    except ValueError as exc:
        raise err(400, "script", str(exc)) from exc
    return {"started": started}
