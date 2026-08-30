"""The console's own listener: the same app, bound a second time on loopback.

The public port is what the proxy (and the classroom wifi) reaches; the
instructor console should not be on it at all. So the app is served twice —
uvicorn's CLI binds the public port, and the lifespan binds ADMIN_HOST:ADMIN_PORT
here — and `AdminPortGate` (api/auth.py) answers 404 for the console's paths
on any listener but this one, telling them apart by `scope["server"]`, the
local address uvicorn records for every accepted connection.

A nested uvicorn.Server with `lifespan="off"`: the app's real lifespan is
already running (it is what calls this), and must not run twice. Only
`startup()`/`shutdown()` are used — no signal handling, no main loop; the
outer server owns both.
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from ..config import Settings

log = logging.getLogger(__name__)


async def start(app: FastAPI, settings: Settings) -> uvicorn.Server | None:
    """Bind the console listener, or None when ADMIN_PORT=0 (console on the
    public port). A busy port exits the process, the way a busy PORT does —
    a room whose console is unreachable should fail at `systemctl start`."""
    if not settings.admin_port:
        return None
    config = uvicorn.Config(app, host=settings.admin_host, port=settings.admin_port,
                            lifespan="off", log_config=None, proxy_headers=False)
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)  # LifespanOff: a no-op
    try:
        await server.startup()
    except SystemExit as exc:  # uvicorn's answer to a busy port: say which, then fail the boot
        raise RuntimeError(
            f"ADMIN_PORT {settings.admin_port} on {settings.admin_host} could not be bound "
            f"(in use? `ss -ltnp 'sport = :{settings.admin_port}'`) — the console would be "
            "unreachable, so the server refuses to start; rooms take 8121+N") from exc
    log.info("admin console on http://%s:%d/admin (404 on the public port; "
             "ssh -L %d:%s:%d to reach it)", settings.admin_host, settings.admin_port,
             settings.admin_port, settings.admin_host, settings.admin_port)
    return server


async def stop(server: uvicorn.Server | None) -> None:
    if server is not None:
        await server.shutdown()
