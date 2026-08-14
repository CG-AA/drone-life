"""In-process event bus: one emit() fans out to the feed ring buffer and any
listeners (the WS hub). Deliberately synchronous and tiny.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

Listener = Callable[[dict], None]


class EventBus:
    def __init__(self, feed_size: int = 200) -> None:
        self.feed: deque[dict] = deque(maxlen=feed_size)
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def emit(self, kind: str, msg: str, student_id: str | None = None,
             data: dict | None = None, t: float = 0.0) -> None:
        event = {"kind": kind, "msg": msg, "student_id": student_id,
                 "data": data or {}, "t": round(t, 2)}
        self.feed.append(event)
        for listener in self._listeners:
            listener(event)
