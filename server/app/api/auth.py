"""Auth: room code to join, per-student bearer tokens, admin token header."""

from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Callable

from fastapi import Header, HTTPException, Request

from ..core.registry import Student
from ..service import DroneLifeService


def err(status: int, code: str, msg: str, **extra) -> HTTPException:
    return HTTPException(status, detail={"code": code, "msg": msg, **extra})


def constant_time_eq(a: str, b: str) -> bool:
    """Timing-safe equality for secrets (room codes, admin tokens).

    The encode matters: compare_digest raises TypeError on non-ASCII str, so a
    student pasting an accented room code would get a 500 instead of a 403.
    surrogatepass covers the rest — a JSON body may carry a lone surrogate
    (`{"room_code": "\\ud800"}`), which plain .encode() refuses.
    """
    return hmac.compare_digest(_utf8(a), _utf8(b))


def _utf8(value: str) -> bytes:
    """Bytes for any str a client can send — never raises."""
    return value.encode("utf-8", "surrogatepass")


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
    """Tiny sliding-window per-key limiter (room-code guessing, submit spam).

    Keys are caller-supplied (client IPs, student ids), so stale ones are swept
    once a minute — otherwise the dict grows for the life of the process.
    """

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self.hits: dict[str, deque[float]] = {}
        self._last_sweep = clock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        if now - self._last_sweep > 60:
            self._sweep(now)
        window = self.hits.setdefault(key, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True

    def blocked(self, key: str) -> bool:
        """Whether this key is at its ceiling — a peek that spends nothing.

        Lets a caller refuse *every* request from a key that has been guessing,
        including correct ones: answering correct-vs-wrong while refusing to
        charge for it would leave the endpoint an oracle with no ceiling at all.
        """
        window = self.hits.get(key)
        if not window:
            return False
        now = self.clock()
        return sum(1 for hit in window if now - hit <= 60) >= self.per_minute

    def _sweep(self, now: float) -> None:
        self._last_sweep = now
        stale = [key for key, window in self.hits.items() if not window or now - window[-1] > 60]
        for key in stale:
            del self.hits[key]


class StrikeGuard:
    """Three wrong room codes and the address is out.

    The sliding-window limiter above caps guessing *speed*; this caps the
    *count*: `strikes` wrong codes lock an address out for `lockout_s` seconds
    (0 = until the server restarts), correct code or not — a locked address
    must learn nothing. A correct code before the ceiling wipes the address's
    slate, so a student who typos twice is not one more typo from a lockout.
    `strikes == 0` disables the guard.
    """

    def __init__(self, strikes: int, lockout_s: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.strikes = strikes
        self.lockout_s = lockout_s
        self.clock = clock
        self.misses: dict[str, list[float]] = {}
        self.locked_at: dict[str, float] = {}

    def blocked(self, key: str) -> bool:
        since = self.locked_at.get(key)
        if since is None:
            return False
        if self.lockout_s and self.clock() - since > self.lockout_s:
            self.clear(key)
            return False
        return True

    def strike(self, key: str) -> None:
        if not self.strikes:
            return
        misses = self.misses.setdefault(key, [])
        misses.append(self.clock())
        if len(misses) >= self.strikes:
            self.locked_at[key] = self.clock()

    def clear(self, key: str) -> None:
        self.misses.pop(key, None)
        self.locked_at.pop(key, None)

    def unlock_all(self) -> int:
        n = len(self.locked_at)
        self.misses.clear()
        self.locked_at.clear()
        return n


def gate_room_code(app_state, ip: str, code: str) -> str:
    """Every endpoint that accepts a room code passes through here.

    Returns "ok", "wrong", "rate" or "locked" and does the bookkeeping. A
    locked or rate-limited address gets the same refusal for right and wrong
    codes (no oracle); a wrong code costs one strike and one unit of join
    budget; a right code clears the address's strikes.
    """
    strikes: StrikeGuard = app_state.join_strikes
    limiter: RateLimiter = app_state.join_limiter
    if strikes.blocked(ip):
        return "locked"
    if limiter.blocked(ip):
        return "rate"
    if not constant_time_eq(code.strip(), app_state.service.settings.room_code):
        limiter.allow(ip)
        strikes.strike(ip)
        return "wrong"
    strikes.clear(ip)
    return "ok"


REFUSALS = {
    "wrong": (403, "room_code", "wrong room code — ask your instructor"),
    "rate": (429, "rate", "too many attempts; wait a minute"),
    "locked": (429, "locked",
               "too many wrong room codes — this address is locked out; ask your instructor"),
}


def refuse(verdict: str) -> HTTPException:
    status, code, msg = REFUSALS[verdict]
    return err(status, code, msg)
