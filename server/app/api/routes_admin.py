"""Instructor endpoints, guarded by X-Admin-Token — and by the admin listener:
they answer only on ADMIN_PORT (auth.AdminPortGate, admin_listener.py)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import mission_choice
from ..game.missions import MISSIONS
from ..runner.manager import RunnerError
from ..service import BOT_SCRIPTS, DroneLifeService
from .auth import err, get_service, require_admin

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


class StudentBody(BaseModel):
    student_id: str


class BotsBody(BaseModel):
    count: int = 5
    script: str = "bot_patrol"
    mode: str = "local"  # "local" (plain subprocess) | "container" (full pipeline)


class RestartBody(BaseModel):
    mission: str | None = None  # None: restart into whatever boots today
    keep_score: bool = False  # SESSION_PLAN Box B: carry the score across the switch


class BanBody(BaseModel):
    name: str = ""
    ip: str = ""


class UnlockBody(BaseModel):
    ip: str = ""  # empty: every lockout


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


@router.get("/info")
async def info(service: DroneLifeService = Depends(get_service)) -> dict:
    """What this process is: the room, the mission and where it came from, and
    the lists the console's dropdowns are built from."""
    s = service.settings
    return {
        "room": s.room_id, "label": s.room_label,
        "mission": service.engine.mission.name,
        "mission_env": s.mission,
        "mission_override": mission_choice.read_override(s),
        "missions": sorted(MISSIONS),
        "bot_scripts": sorted(BOT_SCRIPTS),
        "supervised": service.supervised,
        "admin_port": s.admin_port,
        "uptime_s": round(time.monotonic() - service._started_at, 1),
    }


@router.post("/reset")
async def reset(service: DroneLifeService = Depends(get_service)) -> dict:
    await service.reset_world()
    return {"ok": True, "epoch": service.world.epoch}


@router.post("/restart")
async def restart(body: RestartBody, service: DroneLifeService = Depends(get_service)) -> dict:
    """Restart the process — into another mission when one is named. The
    override file is written first, the response goes out, then the process
    leaves; systemd brings it back (`supervised`), a dev server does not."""
    if body.mission is not None and body.mission not in MISSIONS:
        raise err(400, "mission", f"unknown mission {body.mission!r}; "
                                  f"one of: {', '.join(sorted(MISSIONS))}")
    if service.restarting:
        raise err(409, "restarting", "already restarting")
    await service.prepare_restart(body.mission, body.keep_score)
    mission = body.mission or mission_choice.effective_mission(service.settings)[0]
    reason = f"switching to {mission}" if body.mission else "server restarting"
    service.request_restart(reason)
    return {"restarting": True, "mission": mission, "supervised": service.supervised}


@router.post("/mission/clear-override")
async def clear_override(service: DroneLifeService = Depends(get_service)) -> dict:
    """Hand the room back to MISSION= at its next boot. No restart."""
    return {"cleared": mission_choice.clear_override(service.settings),
            "mission_env": service.settings.mission}


@router.post("/kill")
async def kill(body: StudentBody, service: DroneLifeService = Depends(get_service)) -> dict:
    return {"stopped": await service.runner.stop(body.student_id)}


@router.post("/kick")
async def kick(body: StudentBody, service: DroneLifeService = Depends(get_service)) -> dict:
    if not await service.kick(body.student_id):
        raise err(404, "student", f"no student {body.student_id!r}")
    return {"ok": True}


@router.post("/ban")
async def ban(body: StudentBody, service: DroneLifeService = Depends(get_service)) -> dict:
    """Kick and keep out: the name cannot rejoin, and the address it joined
    from is refused everywhere (mind a shared wifi: that is everyone behind
    it). Until unbanned from the console; bans survive a restart."""
    student = await service.ban(body.student_id)
    if student is None:
        raise err(404, "student", f"no student {body.student_id!r}")
    return {"ok": True, "address_locked": bool(student.ip)}


@router.get("/bans")
async def bans(request: Request, service: DroneLifeService = Depends(get_service)) -> dict:
    """The keep-out list: banned names, banned addresses, and the strike
    guard's automatic lockouts (three wrong room codes)."""
    return {**service.bans.to_dict(), "lockouts": request.app.state.join_strikes.locked()}


@router.post("/bans")
async def add_ban(body: BanBody, service: DroneLifeService = Depends(get_service)) -> dict:
    name, ip = body.name.strip(), body.ip.strip()
    if not name and not ip:
        raise err(400, "ban", "give a name or an address to ban")
    return {"kicked": await service.ban_key(name, ip)}


@router.post("/unban")
async def unban(body: BanBody, service: DroneLifeService = Depends(get_service)) -> dict:
    name, ip = body.name.strip(), body.ip.strip()
    if not name and not ip:
        raise err(400, "ban", "give the name or address to unban")
    removed = False
    if name:
        removed = service.bans.unban_name(name) or removed
    if ip:
        removed = service.bans.unban_ip(ip) or removed
    service._save_snapshot()
    return {"removed": removed}


@router.post("/bans/clear")
async def clear_bans(service: DroneLifeService = Depends(get_service)) -> dict:
    n = service.bans.clear()
    service._save_snapshot()
    return {"unbanned": n}


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


@router.post("/unlock")
async def unlock(request: Request, body: UnlockBody | None = None,
                 _: None = Depends(require_admin)) -> dict:
    """Lift the room-code lockouts (a student who typoed three times) — one
    address, or all of them. Bans are a list of their own: /unban, /bans/clear."""
    strikes = request.app.state.join_strikes
    if body is not None and body.ip.strip():
        ip = body.ip.strip()
        was = strikes.blocked(ip)
        strikes.clear(ip)
        return {"unlocked": int(was)}
    return {"unlocked": strikes.unlock_all()}
