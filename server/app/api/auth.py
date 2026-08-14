"""Auth: room code to join, per-student bearer tokens, admin token header."""

from __future__ import annotations

import time
from collections import deque

from fastapi import Header, HTTPException, Request

from ..core.registry import Student
from ..service import DroneLifeService


def err(status: int, code: str, msg: str, **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "msg": msg, **extra})


def get_service(request: Request) -> DroneLifeService:
    return request.app.state.service


def require_student(request: Request, authorization: str = Header("")) -> Student:
    token = authorization.removeprefix("Bearer ").strip()
    student = request.app.state.service.registry.by_token(token) if token else None
    if student is None:
        raise err(401, "auth", "join first (bad or missing token)")
    return student


def require_admin(request: Request, x_admin_token: str = Header("")) -> None:
    if x_admin_token != request.app.state.service.settings.admin_token:
        raise err(403, "auth", "bad admin token")


class RateLimiter:
    """Tiny sliding-window per-key limiter (join endpoint / room-code guessing)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self.hits.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True
