"""WebSocket hub: /ws/viewer and /ws/student.

Backpressure policy: world frames go in a latest-wins slot (a stalled projector
tab silently skips frames, never queues them); events/logs go in a bounded FIFO
that drops oldest on overflow. Every socket gets its own sender task — the
driver loop never awaits a send.

Frames are serialized once per broadcast, not once per client: clients hold
the encoded text, so a room of twenty projector tabs costs one json.dumps per
tick instead of twenty. Hub methods still take plain dicts.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .auth import constant_time_eq

log = logging.getLogger(__name__)
router = APIRouter()

QUEUE_SIZE = 256
LOG_FLUSH_INTERVAL = 0.1


def envelope(type_: str, data: dict) -> dict:
    return {"v": 1, "type": type_, "t": round(time.time(), 2), "data": data}


def encode(type_: str, data: dict) -> str:
    """One wire frame, encoded once for every client that will receive it."""
    return json.dumps(envelope(type_, data))


class Client:
    def __init__(self, ws: WebSocket, student_id: str | None = None) -> None:
        self.ws = ws
        self.student_id = student_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.world: str | None = None
        self.kick = asyncio.Event()

    def push_world(self, msg: str) -> None:
        self.world = msg  # latest wins; stale frames are overwritten, never queued
        self.kick.set()

    def push(self, msg: str) -> None:
        while True:
            try:
                self.queue.put_nowait(msg)
                break
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    break
        self.kick.set()

    async def sender(self) -> None:
        try:
            while True:
                await self.kick.wait()
                self.kick.clear()
                if self.world is not None:
                    world, self.world = self.world, None
                    await self.ws.send_text(world)
                while True:
                    try:
                        msg = self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await self.ws.send_text(msg)
        except Exception as exc:
            # socket died; the receive loop cleans up — but keep a trace so a
            # genuine sender bug is not indistinguishable from a closed tab
            log.debug("ws sender ended: %r", exc)


class Hub:
    def __init__(self, service) -> None:
        self.service = service
        self.clients: set[Client] = set()
        self.by_student: dict[str, set[Client]] = {}
        self._log_buffers: dict[str, list[dict]] = {}
        self._attached_rings: set[str] = set()
        self._flusher: asyncio.Task | None = None
        service.bus.subscribe(self._on_bus_event)
        service.hub = self

    def start(self) -> None:
        self._flusher = asyncio.create_task(self._flush_logs(), name="log-flusher")

    async def stop(self) -> None:
        if self._flusher:
            self._flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flusher
            self._flusher = None

    # ------------------------------------------------- called by the service

    def broadcast_world(self, data: dict) -> None:
        msg = encode("world", data)
        for client in self.clients:
            client.push_world(msg)

    def broadcast_tiles(self, data: dict) -> None:
        msg = encode("tiles", data)
        for client in self.clients:
            client.push(msg)

    def send_run_state(self, student_id: str, payload: dict) -> None:
        targets = self.by_student.get(student_id)
        if not targets:
            return
        msg = encode("run_state", payload)
        for client in targets:
            client.push(msg)

    def _on_bus_event(self, event: dict) -> None:
        msg = encode("event", event)
        for client in self.clients:
            client.push(msg)

    # ------------------------------------------------------------- log fanout

    def attach_ring(self, student_id: str) -> None:
        if student_id in self._attached_rings:
            return
        self._attached_rings.add(student_id)
        ring = self.service.runner.log_for(student_id)
        ring.listeners.append(
            lambda entry, sid=student_id: self._log_buffers.setdefault(sid, []).append(entry))

    async def _flush_logs(self) -> None:
        while True:
            await asyncio.sleep(LOG_FLUSH_INTERVAL)
            for student_id in list(self._log_buffers):
                lines = self._log_buffers.pop(student_id, [])
                targets = self.by_student.get(student_id)
                if lines and targets:
                    msg = encode("log", {"lines": lines})
                    for client in targets:
                        client.push(msg)

    # ------------------------------------------------------------ connections

    def register(self, client: Client) -> None:
        self.clients.add(client)
        if client.student_id:
            self.by_student.setdefault(client.student_id, set()).add(client)
            self.attach_ring(client.student_id)

    def unregister(self, client: Client) -> None:
        self.clients.discard(client)
        if client.student_id:
            self.by_student.get(client.student_id, set()).discard(client)


async def _serve(ws: WebSocket, client: Client) -> None:
    hub: Hub = ws.app.state.hub
    service = ws.app.state.service
    hub.register(client)
    client.push(encode("hello", service.hello_message()))
    if service.tilemap is not None:
        client.push(encode("tiles", service.tiles_message()))
    for event in list(service.bus.feed)[-20:]:
        client.push(encode("event", event))
    client.push_world(encode("world", service.world_message()))
    sender = asyncio.create_task(client.sender())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                client.push(encode("pong", {}))
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        hub.unregister(client)


@router.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket) -> None:
    service = ws.app.state.service
    code = ws.query_params.get("code", "").strip()
    if not constant_time_eq(code, service.settings.room_code):
        await ws.close(code=4403)
        return
    await ws.accept()
    await _serve(ws, Client(ws))


@router.websocket("/ws/student")
async def ws_student(ws: WebSocket) -> None:
    service = ws.app.state.service
    student = service.registry.by_token(ws.query_params.get("token", ""))
    if student is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    client = Client(ws, student_id=student.id)
    run = service.runner.run_for(student.id)
    if run is not None:
        client.push(encode("run_state", run.payload()))
    tail = service.runner.log_for(student.id).tail(50)
    if tail:
        client.push(encode("log", {"lines": tail}))
    await _serve(ws, client)
