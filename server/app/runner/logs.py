"""Per-student log ring buffer with live listeners (the WS hub subscribes)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

MAX_LINE = 4096

Listener = Callable[[dict], None]


class RingLog:
    def __init__(self, maxlen: int = 2000) -> None:
        self.lines: deque[dict] = deque(maxlen=maxlen)
        self.listeners: list[Listener] = []

    def append(self, stream: str, line: str) -> None:
        entry = {"ts": round(time.time(), 2), "stream": stream, "line": line[:MAX_LINE]}
        self.lines.append(entry)
        for listener in self.listeners:
            listener(entry)

    def tail(self, n: int = 50) -> list[dict]:
        return list(self.lines)[-n:]
