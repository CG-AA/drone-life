"""Per-drone MAVLink TCP endpoints on loopback.

One listener per drone at 127.0.0.1:base_port+slot. Identity is the port — no
sysid trust needed from the client. Exactly one connection per drone; a new
connection wins (resubmits must always be able to take over). TCP close is the
script-death signal: after a sim-time grace period an airborne drone auto-RTLs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..sim import params as P
from ..sim.drone import DroneSim
from ..sim.world import World
from . import handlers, telemetry
from .wire import SEV_WARNING, Link

log = logging.getLogger(__name__)


@dataclass
class Conn:
    link: Link
    writer: asyncio.StreamWriter


class Gateway:
    def __init__(self, world: World, host: str, base_port: int) -> None:
        self.world = world
        self.host = host
        self.base_port = base_port
        self.servers: dict[str, asyncio.Server] = {}
        self.conns: dict[str, Conn] = {}
        self.orphan_tasks: dict[str, asyncio.Task] = {}

    def port_for_slot(self, slot: int) -> int:
        return self.base_port + slot

    async def start_listener(self, drone: DroneSim, slot: int) -> int:
        port = self.port_for_slot(slot)
        server = await asyncio.start_server(
            lambda r, w: self._handle(drone, r, w), self.host, port
        )
        self.servers[drone.id] = server
        return port

    async def stop_listener(self, drone_id: str) -> None:
        server = self.servers.pop(drone_id, None)
        if server:
            server.close()
            await server.wait_closed()
        conn = self.conns.pop(drone_id, None)
        if conn:
            conn.writer.close()
        task = self.orphan_tasks.pop(drone_id, None)
        if task:
            task.cancel()

    async def stop_all(self) -> None:
        for drone_id in list(self.servers):
            await self.stop_listener(drone_id)

    async def _handle(
        self, drone: DroneSim, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        old = self.conns.get(drone.id)
        if old is not None:
            try:
                old.link.statustext("replaced by a new connection", SEV_WARNING)
                old.writer.close()
            except (OSError, RuntimeError) as exc:  # already-dead transport
                log.debug("closing replaced connection for %s: %r", drone.id, exc)
        task = self.orphan_tasks.pop(drone.id, None)
        if task:
            task.cancel()

        link = Link(writer, drone.sysid)
        conn = Conn(link=link, writer=writer)
        self.conns[drone.id] = conn
        # texts queued while nobody was listening are history, not news: a
        # mid-round joiner used to receive every announce since boot (stale
        # gates, old build sites) before its first heartbeat. Missions brief a
        # newcomer themselves on the "connected" event.
        drone.outbox.clear()
        drone.connected = True
        drone.events.append("connected")
        # immediate heartbeat so the client's wait_heartbeat() returns right away
        telemetry.send_heartbeat(link, drone)
        try:
            await writer.drain()
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                for msg in link.parse(data):
                    try:
                        handlers.handle(link, drone, msg, self.world.t)
                    except Exception:
                        log.exception("drone %s: handler error for %s", drone.id, msg.get_type())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception:
            log.exception("drone %s: connection error", drone.id)
        finally:
            writer.close()
            if self.conns.get(drone.id) is conn:
                del self.conns[drone.id]
                drone.connected = False
                drone.events.append("disconnected")
                self.orphan_tasks[drone.id] = asyncio.create_task(self._orphan_watch(drone))

    async def _orphan_watch(self, drone: DroneSim) -> None:
        """Sim-time grace, then fly the abandoned drone home."""
        deadline = self.world.t + P.ORPHAN_GRACE
        while self.world.t < deadline:  # noqa: ASYNC110 — polling SIM time, no event exists
            await asyncio.sleep(0.05)
        if not drone.connected and drone.armed and not drone.on_ground and not drone.crashed:
            drone.set_mode(P.MODE_RTL, self.world.t)
            drone.say("script gone: returning home", SEV_WARNING)
            drone.events.append("orphan_rtl")
        self.orphan_tasks.pop(drone.id, None)

    async def telemetry_tick(self, tick: int) -> None:
        """Called by the driver every sim tick."""
        for drone_id, conn in list(self.conns.items()):
            drone = self.world.drones.get(drone_id)
            if drone is None:
                continue
            try:
                telemetry.send_tick(conn.link, drone, self.world.t, tick)
                await conn.writer.drain()
            except (ConnectionResetError, BrokenPipeError):
                conn.writer.close()
            except Exception:
                log.exception("telemetry to drone %s failed", drone_id)
