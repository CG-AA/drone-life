"""WebSocket handshake: a rejection must arrive as its own close code.

Closing before the handshake completes reaches a browser as a plain 1006,
indistinguishable from a dead server — so the submit page retried a dead
token forever instead of showing the join form. These tests drive the ASGI
websocket protocol directly; httpx has no WebSocket transport.
"""

import asyncio
import json

from .conftest import make_settings, running_app


async def ws_session(app, path: str, query: str, want: int = 1) -> list[dict]:
    """Connect, collect up to `want` server messages, then disconnect."""
    incoming: asyncio.Queue = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    sent: list[dict] = []
    done = asyncio.Event()

    async def receive() -> dict:
        if done.is_set():
            return {"type": "websocket.disconnect", "code": 1000}
        return await incoming.get()

    async def send(message: dict) -> None:
        sent.append(message)
        if message["type"] == "websocket.close" or len(sent) >= want:
            done.set()
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    scope = {
        "type": "websocket", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "scheme": "ws", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "root_path": "", "headers": [],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "subprotocols": [],
    }
    async with asyncio.timeout(5):
        await app(scope, receive, send)
    return sent


def frames(sent: list[dict]) -> list[dict]:
    return [json.loads(m["text"]) for m in sent if m["type"] == "websocket.send"]


async def test_viewer_with_a_bad_room_code_is_accepted_then_closed_4403(tmp_path):
    async with running_app(make_settings(tmp_path)) as app:
        sent = await ws_session(app, "/ws/viewer", "code=not-the-code")

    assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
    assert sent[-1]["code"] == 4403


async def test_student_with_a_stale_token_is_accepted_then_closed_4401(tmp_path):
    async with running_app(make_settings(tmp_path)) as app:
        sent = await ws_session(app, "/ws/student", "token=long-expired")

    assert [m["type"] for m in sent] == ["websocket.accept", "websocket.close"]
    assert sent[-1]["code"] == 4401


async def test_viewer_with_the_room_code_gets_the_world(tmp_path):
    settings = make_settings(tmp_path)
    async with running_app(settings) as app:
        sent = await ws_session(app, "/ws/viewer", f"code={settings.room_code}", want=6)

    assert sent[0]["type"] == "websocket.accept"
    kinds = {frame["type"] for frame in frames(sent)}
    assert {"hello", "world"} <= kinds


async def test_student_with_a_live_token_gets_attached(tmp_path):
    settings = make_settings(tmp_path)
    async with running_app(settings) as app:
        student, _ = await app.state.service.join("Zoe")
        sent = await ws_session(app, "/ws/student", f"token={student.token}", want=6)

    assert sent[0]["type"] == "websocket.accept"
    assert "hello" in {frame["type"] for frame in frames(sent)}
