"""Who's in the class: students, their tokens, their drone slots."""

from __future__ import annotations

import hmac
import logging
import re
import secrets
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)


@dataclass
class Student:
    id: str  # "s<slot>"
    name: str
    token: str
    slot: int
    sysid: int
    port: int
    ip: str = ""  # where the last join came from; what a ban locks out


class RoomFullError(Exception):
    pass


class Registry:
    def __init__(self, max_students: int, base_port: int) -> None:
        self.max_students = max_students
        self.base_port = base_port
        self.students: dict[str, Student] = {}  # by id
        self.banned_names: set[str] = set()  # normalized; until restart or unlock

    def by_token(self, token: str) -> Student | None:
        # constant-time per candidate; the scan itself only leaks the roster size.
        # surrogatepass: a bearer token is client-supplied and must never crash
        # the compare (a lone surrogate makes plain .encode() raise)
        want = token.encode("utf-8", "surrogatepass")
        for student in self.students.values():
            if hmac.compare_digest(student.token.encode("utf-8", "surrogatepass"), want):
                return student
        return None

    def by_name(self, name: str) -> Student | None:
        key = _norm(name)
        return next((s for s in self.students.values() if _norm(s.name) == key), None)

    def is_banned(self, name: str) -> bool:
        return _norm(name) in self.banned_names

    def ban_name(self, name: str) -> None:
        self.banned_names.add(_norm(name))

    def unban_all(self) -> int:
        n = len(self.banned_names)
        self.banned_names.clear()
        return n

    def join(self, name: str, ip: str = "") -> tuple[Student, bool]:
        """Returns (student, is_new). Rejoining with the same name rotates the
        token but keeps the same slot/drone — refresh-proof for students."""
        existing = self.by_name(name)
        if existing:
            existing.token = secrets.token_urlsafe(16)
            existing.ip = ip or existing.ip
            return existing, False
        used = {s.slot for s in self.students.values()}
        slot = next((i for i in range(self.max_students) if i not in used), None)
        if slot is None:
            raise RoomFullError(f"room is full ({self.max_students} drones)")
        student = Student(
            id=f"s{slot}", name=name.strip()[:24], token=secrets.token_urlsafe(16),
            slot=slot, sysid=slot + 1, port=self.base_port + slot, ip=ip,
        )
        self.students[student.id] = student
        return student, True

    def remove(self, student_id: str) -> Student | None:
        return self.students.pop(student_id, None)

    def to_dict(self) -> list[dict]:
        return [asdict(s) for s in self.students.values()]

    def restore(self, rows: list[dict]) -> None:
        for row in rows:
            try:
                s = Student(**row)
                self.students[s.id] = s
            except TypeError:
                log.warning("snapshot row skipped (old schema): %r", row)


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()
