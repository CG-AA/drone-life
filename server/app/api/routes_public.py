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
from .auth import constant_time_eq, err, get_service, require_student

router = APIRouter(prefix="/api/v1")

MAX_CODE_BYTES = 64 * 1024
TEMPLATES = {
    "beginner": "template.py",
    "pymavlink": "template_pymavlink.py",
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
    if not request.app.state.join_limiter.allow(ip):
        raise err(429, "rate", "too many join attempts; wait a minute")
    if not constant_time_eq(body.room_code.strip(), service.settings.room_code):
        raise err(403, "room_code", "wrong room code — ask your instructor")
    name = body.name.strip()
    if not (1 <= len(name) <= 24):
        raise err(400, "name", "pick a name between 1 and 24 characters")
    if name.lower().startswith("bot-"):
        raise err(400, "name", "names starting with 'Bot-' are reserved")
    try:
        student, is_new = await service.join(name)
    except RoomFullError as exc:
        raise err(409, "room_full", str(exc)) from exc
    pad = service.world.pad_position(student.slot)
    return {
        "token": student.token, "student_id": student.id, "name": student.name,
        "slot": student.slot, "sysid": student.sysid,
        "spawn": {"n": pad[0], "e": pad[1]}, "rejoined": not is_new,
    }


@router.get("/template")
async def template(variant: str = "beginner") -> PlainTextResponse:
    filename = TEMPLATES.get(variant)
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
        "run": run.payload() if run else None,
        "drone": asdict(DroneView.of(drone)) if drone else None,
        "log_tail": service.runner.log_for(student.id).tail(50),
    }


@router.get("/world")
async def world(request: Request, code: str = "",
                service: DroneLifeService = Depends(get_service)) -> dict:
    # a wrong code here is a room-code guess like any other, so it spends the
    # join budget. Once that budget is gone every answer is 429, right code or
    # wrong — answering the correct one while refusing to charge for guesses
    # would leave an oracle with no ceiling at all.
    ip = request.client.host if request.client else "?"
    limiter = request.app.state.join_limiter
    if limiter.blocked(ip):
        raise err(429, "rate", "too many attempts; wait a minute")
    if not constant_time_eq(code.strip(), service.settings.room_code):
        limiter.allow(ip)
        raise err(403, "room_code", "wrong room code")
    return {"world": service.world_message(), "feed": list(service.bus.feed)[-30:],
            "hello": service.hello_message()}
