"""Student-facing REST API."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..core.registry import RoomFullError, Student
from ..runner.manager import RunnerError
from ..service import EXAMPLES_DIR, DroneLifeService
from ..sim.backend import DroneView
from .auth import err, gate_room_code, get_service, refuse, require_student

router = APIRouter(prefix="/api/v1")

MAX_CODE_BYTES = 64 * 1024
# starters first, then the demo bots (the same scripts the instructor console
# spawns) — a worked example is the fastest way past a blank page
TEMPLATES = {
    "beginner": "template.py",
    "delivery": "template_delivery.py",
    "siege": "template_siege.py",
    "pymavlink": "template_pymavlink.py",
    "bot_courier": "bot_courier.py",
    "bot_siege": "bot_siege.py",
    "bot_tower": "bot_tower.py",
    "bot_repair": "bot_repair.py",
    "bot_scout": "bot_scout.py",
    "bot_builder": "bot_builder.py",
    "bot_patrol": "bot_patrol.py",
}


class JoinBody(BaseModel):
    room_code: str = ""
    name: str = ""


class SubmitBody(BaseModel):
    code: str


@router.post("/join")
async def join(body: JoinBody, request: Request,
               service: DroneLifeService = Depends(get_service)) -> dict:
    ip = request.client.host if request.client else "?"
    verdict = gate_room_code(request.app.state, ip, body.room_code)
    if verdict != "ok":
        raise refuse(verdict)
    request.app.state.join_limiter.allow(ip)  # correct joins spend budget too: no join spam
    name = body.name.strip()
    if not (1 <= len(name) <= 24):
        raise err(400, "name", "pick a name between 1 and 24 characters")
    if name.lower().startswith("bot-"):
        raise err(400, "name", "names starting with 'Bot-' are reserved")
    if service.registry.is_banned(name):
        raise err(403, "banned", "this name is banned — ask your instructor")
    try:
        student, is_new = await service.join(name, ip)
    except RoomFullError as exc:
        raise err(409, "room_full", str(exc)) from exc
    pad = service.world.pad_position(student.slot)
    return {
        "token": student.token, "student_id": student.id, "name": student.name,
        "slot": student.slot, "sysid": student.sysid,
        "spawn": {"n": pad[0], "e": pad[1]}, "rejoined": not is_new,
    }


def default_variant(mission: str) -> str:
    """The starter a fresh editor loads: the teaching game and the main event
    get their own, so a student joining mid-siege is not handed a first-flight
    script."""
    return mission if mission in ("delivery", "siege") else "beginner"


@router.get("/rooms")
async def rooms(service: DroneLifeService = Depends(get_service)) -> dict:
    """The small rooms behind the proxy (docs/ROOMS.md). The student page lists
    them and reads each one's own /healthz for the live count. Unauthenticated
    and unlimited on purpose: it names nothing that list would not show."""
    return {"rooms": [{"id": r, "path": f"/{r}"} for r in service.settings.room_list]}


@router.get("/template")
async def template(variant: str = "",
                   service: DroneLifeService = Depends(get_service)) -> PlainTextResponse:
    filename = TEMPLATES.get(variant or default_variant(service.engine.mission.name))
    if filename is None:
        raise err(404, "variant", f"unknown template variant {variant!r}")
    # off-loop: this route shares the event loop with the 20 Hz sim driver
    return PlainTextResponse(await asyncio.to_thread((EXAMPLES_DIR / filename).read_text))


@router.post("/submit")
async def submit(body: SubmitBody, request: Request,
                 student: Student = Depends(require_student),
                 service: DroneLifeService = Depends(get_service)) -> dict:
    # first, before the size check and the parse: a submit loop costs a podman
    # start and a 64 KB parse on the driver's event loop
    if not request.app.state.submit_limiter.allow(student.id):
        raise err(429, "rate", "submitting too fast — wait a few seconds")
    code = body.code
    if len(code.encode()) > MAX_CODE_BYTES:
        raise err(413, "too_big", "script larger than 64 KB")
    try:
        # instant feedback: a missing colon costs one second, not a container start
        ast.parse(code, filename="your_script.py")
    except SyntaxError as exc:
        raise err(400, "syntax", f"syntax error: {exc.msg}",
                  line=exc.lineno or 0, col=exc.offset or 0) from exc
    try:
        run_id = await service.runner.submit_container(student, code)
    except RunnerError as exc:
        raise err(503, "runner", f"could not start your drone box: {exc}") from exc
    return {"run_id": run_id}


@router.post("/stop")
async def stop(student: Student = Depends(require_student),
               service: DroneLifeService = Depends(get_service)) -> dict:
    return {"stopped": await service.runner.stop(student.id)}


@router.post("/reset-mine")
async def reset_mine(student: Student = Depends(require_student),
                     service: DroneLifeService = Depends(get_service)) -> dict:
    await service.reset_mine(student)
    return {"ok": True}


@router.get("/status")
async def status(student: Student = Depends(require_student),
                 service: DroneLifeService = Depends(get_service)) -> dict:
    run = service.runner.run_for(student.id)
    drone = service.world.drones.get(service.drone_id_for(student))
    return {
        "student_id": student.id,
        "name": student.name,  # both can change under a stored token: rooms merge (ROOMS.md)
        "run": run.payload() if run else None,
        "drone": asdict(DroneView.of(drone)) if drone else None,
        "log_tail": service.runner.log_for(student.id).tail(50),
    }


@router.get("/world")
async def world(request: Request, code: str = "",
                service: DroneLifeService = Depends(get_service)) -> dict:
    # a wrong code here is a room-code guess like any other: it spends the
    # join budget and earns a strike (auth.gate_room_code has the reasoning)
    ip = request.client.host if request.client else "?"
    verdict = gate_room_code(request.app.state, ip, code)
    if verdict != "ok":
        raise refuse(verdict)
    return {"world": service.world_message(), "feed": list(service.bus.feed)[-30:],
            "hello": service.hello_message()}
