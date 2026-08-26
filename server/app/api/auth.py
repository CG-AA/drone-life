"""Auth: room code to join, per-student bearer tokens, admin token header."""

from __future__ import annotations

import hmac
import time
from collections import deque

from fastapi import Header, HTTPException, Request

from ..core.registry import Student
from ..service import DroneLifeService


def err(status: int, code: str, msg: str, **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "msg": msg, **extra})


def constant_time_eq(a: str, b: str) -> bool:
    """Timing-safe equality for secrets (room codes, admin tokens).

    The encode matters: compare_digest raises TypeError on non-ASCII str, so a
    student pasting an accented room code would get a 500 instead of a 403.
    """
    return hmac.compare_digest(a.encode(), b.encode())


def get_service(request: Request) -> DroneLifeService:
    return request.app.state.service


def require_student(request: Request, authorization: str = Header("")) -> Student:
    token = authorization.removeprefix("Bearer ").strip()
    student = request.app.state.service.registry.by_token(token) if token else None
    if student is None:
        raise err(401, "auth", "join first (bad or missing token)")
    return student


def require_admin(request: Request, x_admin_token: str = Header("")) -> None:
    if not constant_time_eq(x_admin_token, request.app.state.service.settings.admin_token):
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
