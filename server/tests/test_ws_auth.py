"""WS auth audit: /ws/viewer and /ws/student must gate before accept().

Sync tests on purpose — TestClient drives the real ASGI handshake (httpx's
ASGITransport cannot speak WebSocket), so these pin the close codes a browser
actually sees. TestClient runs the lifespan itself, so the settings must carry
real secrets (the startup guard) and this must never nest inside running_app().
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.conftest import make_settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


def close_code(client, url):
    """The close code the browser sees; connecting at all is the failure."""
    with pytest.raises(WebSocketDisconnect) as excinfo, client.websocket_connect(url):
        pass  # pragma: no cover — the handshake must not get this far
    return excinfo.value.code


def test_viewer_rejects_wrong_room_code(client):
    assert close_code(client, "/ws/viewer?code=nope") == 4403


def test_viewer_rejects_missing_room_code(client):
    assert close_code(client, "/ws/viewer") == 4403


def frame_types(ws, count=4):
    """The sender flushes the latest-wins world slot before the FIFO, so the
    greeting is not reliably frame one — collect a few and look for it."""
    return [ws.receive_json()["type"] for _ in range(count)]


def test_viewer_accepts_room_code_with_stray_whitespace(client):
    """Join strips the pasted code, so the viewer must strip it too."""
    with client.websocket_connect("/ws/viewer?code=%20test-room%20") as ws:
        assert "hello" in frame_types(ws)


def test_viewer_stops_answering_once_guessing_exhausts_the_budget(tmp_path):
    """Same rule as /world: while the ceiling holds, the right code is refused
    too — otherwise the handshake stays a room-code oracle with no ceiling."""
    settings = make_settings(tmp_path, join_rate_limit_per_minute=2)
    with TestClient(create_app(settings)) as c:
        for _ in range(2):
            assert close_code(c, "/ws/viewer?code=nope") == 4403
        assert close_code(c, "/ws/viewer?code=test-room") == 4403


def test_student_rejects_bad_token(client):
    assert close_code(client, "/ws/student?token=bogus") == 4401


def test_student_rejects_missing_token(client):
    assert close_code(client, "/ws/student") == 4401


def test_student_accepts_real_token(client):
    joined = client.post("/api/v1/join", json={"room_code": "test-room", "name": "Wes"})
    assert joined.status_code == 200
    token = joined.json()["token"]
    with client.websocket_connect(f"/ws/student?token={token}") as ws:
        assert "hello" in frame_types(ws)
