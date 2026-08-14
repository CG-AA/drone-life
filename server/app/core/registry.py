"""Who's in the class: students, their tokens, their drone slots."""

from __future__ import annotations

import re
import secrets
from dataclasses import asdict, dataclass


@dataclass
class Student:
    id: str  # "s<slot>"
    name: str
    token: str
    slot: int
    sysid: int
    port: int


class RoomFullError(Exception):
    pass


class Registry:
    def __init__(self, max_students: int, base_port: int) -> None:
        self.max_students = max_students
        self.base_port = base_port
        self.students: dict[str, Student] = {}  # by id

    def by_token(self, token: str) -> Student | None:
        return next((s for s in self.students.values() if s.token == token), None)

    def by_name(self, name: str) -> Student | None:
        key = _norm(name)
        return next((s for s in self.students.values() if _norm(s.name) == key), None)

    def join(self, name: str) -> tuple[Student, bool]:
        """Returns (student, is_new). Rejoining with the same name rotates the
        token but keeps the same slot/drone — refresh-proof for students."""
        existing = self.by_name(name)
        if existing:
            existing.token = secrets.token_urlsafe(16)
            return existing, False
        used = {s.slot for s in self.students.values()}
        slot = next((i for i in range(self.max_students) if i not in used), None)
        if slot is None:
            raise RoomFullError(f"room is full ({self.max_students} drones)")
        student = Student(
            id=f"s{slot}", name=name.strip()[:24], token=secrets.token_urlsafe(16),
            slot=slot, sysid=slot + 1, port=self.base_port + slot,
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
                continue  # snapshot from an older schema: skip


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()
