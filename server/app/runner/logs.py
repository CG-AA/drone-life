"""Per-student log ring buffer with live listeners (the WS hub subscribes)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

MAX_LINE = 4096

# Retention was bounded but throughput was not: `while True: print(...)` pushed
# every line straight through to the hub's listeners. A token bucket caps the
# sustained rate while leaving normal chatty output untouched.
FLOOD_RATE = 50.0  # sustained lines/sec per run
FLOOD_BURST = 200.0  # a burst this size passes at full speed
NOTICE_INTERVAL = 5.0  # seconds between "dropped N lines" notices

Listener = Callable[[dict], None]


class RingLog:
    def __init__(self, maxlen: int = 2000, rate: float = FLOOD_RATE,
                 burst: float = FLOOD_BURST,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.lines: deque[dict] = deque(maxlen=maxlen)
        self.listeners: list[Listener] = []
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._tokens = burst
        self._last_refill = clock()
        self._dropped = 0
        self._last_notice = float("-inf")  # the first drop of a flood notifies at once

    def append(self, stream: str, line: str) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._last_refill) * self._rate)
        self._last_refill = now
        # system lines are ours (run started, script exited) — never drop them
        if stream != "system":
            if self._tokens < 1.0:
                self._dropped += 1
                if now - self._last_notice >= NOTICE_INTERVAL:
                    self._last_notice = now
                    dropped, self._dropped = self._dropped, 0
                    self._emit("system", f"…output flooded, dropped {dropped} lines "
                                         f"(max ~{int(self._rate)}/s)…")
                return
            self._tokens -= 1.0
        self._emit(stream, line)

    def _emit(self, stream: str, line: str) -> None:
        entry = {"ts": round(time.time(), 2), "stream": stream, "line": line[:MAX_LINE]}
        self.lines.append(entry)
        for listener in self.listeners:
            listener(entry)

    def tail(self, n: int = 50) -> list[dict]:
        return list(self.lines)[-n:]
