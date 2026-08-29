"""Running the service with no browser attached: what the load test and the
balance tool share. A NullHub satisfies the service's broadcast seam and
drops everything; find_port_base picks a free MAVLink range on loopback."""

from __future__ import annotations

import random
import socket


class NullHub:
    """The service's WorldSink with nobody listening."""

    def broadcast_world(self, data: dict) -> None:
        pass

    def broadcast_tiles(self, data: dict) -> None:
        pass

    def send_run_state(self, student_id: str, payload: dict) -> None:
        pass


def find_port_base(count: int = 8) -> int:
    """A base with `count` consecutive free TCP ports on loopback."""
    for _ in range(60):
        base = random.randint(20000, 55000)
        socks = []
        try:
            for i in range(count):
                s = socket.socket()
                s.bind(("127.0.0.1", base + i))
                socks.append(s)
            return base
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()
    raise RuntimeError("no free port range found")
