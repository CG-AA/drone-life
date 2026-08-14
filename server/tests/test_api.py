"""REST surface: join flow, syntax gate, status, world, admin."""

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from tests.conftest import find_port_base


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        sim_unthrottled=True,
        mavlink_base_port=find_port_base(),
        state_dir=tmp_path / "state",
        room_code="test-room",
        admin_token="test-admin",
        max_students=4,
        sim_seed=7,
    )
    app = create_app(settings)
    service = app.state.service
    await service.start()
    app.state.hub.start()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.hub.stop()
    await service.stop()


async def join(client, name="Zoe") -> dict:
    r = await client.post("/api/v1/join", json={"room_code": "test-room", "name": name})
    assert r.status_code == 200, r.text
    return r.json()


async def test_join_flow(client):
    data = await join(client)
    assert data["token"] and data["student_id"] == "s0" and data["sysid"] == 1
    # rejoin with the same name: same slot, fresh token
    again = await join(client)
    assert again["student_id"] == "s0" and again["token"] != data["token"]
    assert again["rejoined"] is True


async def test_join_wrong_room_code(client):
    r = await client.post("/api/v1/join", json={"room_code": "nope", "name": "Zed"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "room_code"


async def test_submit_syntax_gate(client):
    token = (await join(client))["token"]
    r = await client.post("/api/v1/submit", json={"code": "def broken(:\n  pass"},
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == "syntax" and error["line"] >= 1


async def test_status_and_world(client):
    token = (await join(client))["token"]
    r = await client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["run"] is None
    assert body["drone"]["on_ground"] is True

    r = await client.get("/api/v1/world", params={"code": "test-room"})
    assert r.status_code == 200
    world = r.json()["world"]
    assert world["score"] == 0
    assert len(world["drones"]) == 1
    kinds = {e["kind"] for e in world["entities"]}
    assert kinds == {"crate", "dropoff"}
    assert sum(1 for e in world["entities"] if e["kind"] == "crate") == 3


async def test_template_served(client):
    r = await client.get("/api/v1/template")
    assert r.status_code == 200 and "dronelife" in r.text
    r = await client.get("/api/v1/template", params={"variant": "pymavlink"})
    assert r.status_code == 200 and "mavutil" in r.text


async def test_admin_reset_and_auth(client):
    r = await client.post("/api/v1/admin/reset")
    assert r.status_code == 403
    r = await client.post("/api/v1/admin/reset", headers={"X-Admin-Token": "test-admin"})
    assert r.status_code == 200 and r.json()["epoch"] == 1


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True
