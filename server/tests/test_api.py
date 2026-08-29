"""REST surface: join flow, syntax gate, status, world, admin."""

import httpx
import pytest

from app.runner.manager import RunnerManager
from tests.conftest import make_settings, running_app

ADMIN = {"X-Admin-Token": "test-admin"}


@pytest.fixture
async def client(tmp_path):
    async with running_app(make_settings(tmp_path, max_students=4)) as app:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


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


async def test_submit_without_runner_image_is_503_with_a_fix(client, monkeypatch):
    """The instructor's fix (`make image`) must reach the student's screen —
    otherwise a missing image is a container that dies with exit 125 in a log
    pane nobody reads."""
    async def no_image(self) -> str | None:
        return f"runner image {self.s.runner_image} is not built — instructor: run `make image`"

    monkeypatch.setattr(RunnerManager, "_image_probe", no_image)
    token = (await join(client))["token"]
    r = await client.post("/api/v1/submit", json={"code": "print('hi')\n"},
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503
    error = r.json()["error"]
    assert error["code"] == "runner" and "make image" in error["msg"]


async def test_bots_without_runner_image_is_503(client, monkeypatch):
    async def no_image(self) -> str | None:
        return "runner image is not built — instructor: run `make image`"

    monkeypatch.setattr(RunnerManager, "_image_probe", no_image)
    r = await client.post("/api/v1/admin/bots", headers=ADMIN,
                          json={"count": 1, "mode": "container", "script": "bot_patrol"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runner"


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
    assert world["mission_state"] == {"crates": 3, "delivered": 0}
    assert len(world["drones"]) == 1
    kinds = {e["kind"] for e in world["entities"]}
    assert kinds == {"crate", "dropoff"}
    assert sum(1 for e in world["entities"] if e["kind"] == "crate") == 3


async def test_template_served(client):
    r = await client.get("/api/v1/template")
    assert r.status_code == 200 and "dronelife" in r.text
    r = await client.get("/api/v1/template", params={"variant": "pymavlink"})
    assert r.status_code == 200 and "mavutil" in r.text
    r = await client.get("/api/v1/template", params={"variant": "siege"})
    assert r.status_code == 200 and "creep" in r.text
    r = await client.get("/api/v1/template", params={"variant": "nope"})
    assert r.status_code == 404


def test_default_template_follows_the_mission():
    from app.api.routes_public import default_variant
    assert default_variant("siege") == "siege"
    assert default_variant("delivery") == "delivery" and default_variant("freefly") == "beginner"


async def test_every_template_variant_is_a_real_parseable_script(client):
    # the submit page's menu is only as good as the files behind it
    import ast

    from app.api.routes_public import TEMPLATES
    for variant in TEMPLATES:
        r = await client.get("/api/v1/template", params={"variant": variant})
        assert r.status_code == 200, variant
        ast.parse(r.text)


async def test_admin_reset_and_auth(client):
    r = await client.post("/api/v1/admin/reset")
    assert r.status_code == 403
    r = await client.post("/api/v1/admin/reset", headers=ADMIN)
    assert r.status_code == 200 and r.json()["epoch"] == 1


async def test_admin_students_roster(client):
    r = await client.get("/api/v1/admin/students")
    assert r.status_code == 403
    await join(client)
    r = await client.get("/api/v1/admin/students", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mission"] and body["score"] == 0
    (row,) = body["students"]
    assert row["student_id"] == "s0" and row["name"] == "Zoe"
    assert row["run"] is None  # nothing submitted yet
    assert row["connected"] is False and row["crashed"] is False


async def test_admin_bots_partial_fill_and_reset_clears_them(client):
    await join(client)  # Zoe takes slot 0 of 4
    # ask for 5: clamped to 4, three fit, then the room is full — partial success
    # must be REPORTED, not discarded
    r = await client.post("/api/v1/admin/bots", headers=ADMIN,
                          json={"count": 5, "script": "bot_patrol", "mode": "local"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["started"]) == 3 and body["room_full"] is True

    # reset clears bots (clean slate for the next session) but keeps students
    r = await client.post("/api/v1/admin/reset", headers=ADMIN)
    assert r.status_code == 200
    world = (await client.get("/api/v1/world", params={"code": "test-room"})).json()["world"]
    assert [d["name"] for d in world["drones"]] == ["Zoe"]

    # and a fresh fleet starts numbering from Bot-1 again
    r = await client.post("/api/v1/admin/bots", headers=ADMIN,
                          json={"count": 2, "script": "bot_patrol", "mode": "local"})
    assert len(r.json()["started"]) == 2
    world = (await client.get("/api/v1/world", params={"code": "test-room"})).json()["world"]
    names = {d["name"] for d in world["drones"]}
    assert {"Zoe", "Bot-1", "Bot-2"} == names


async def test_healthz(client):
    """The admin console reads these keys — dropping one breaks it silently."""
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body) == {"ok", "drones", "ticks", "overruns", "score", "mission",
                         "students", "uptime_s", "driver_alive", "last_tick_age_s",
                         "driver_errors"}


async def test_rampart_tiles_and_terrain_wiring(tmp_path):
    """A tile mission wires its TileMap into the sim and the tiles feed."""
    async with running_app(make_settings(tmp_path, mission="rampart")) as app:
        service = app.state.service
        assert service.tilemap is service.engine.mission.tile_map()
        assert service.world.terrain is service.tilemap

        msg = service.tiles_message()
        assert msg["geometry"]["size"] > 0 and "cells" in msg

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/v1/world", params={"code": "test-room"})
            assert r.status_code == 200
            body = r.json()
            assert body["hello"]["mission"] == "rampart"
            kinds = {e["kind"] for e in body["world"]["entities"]}
            assert "tile_source" in kinds and "ghost_tile" in kinds

            version = service.tilemap.version
            r = await c.post("/api/v1/admin/reset", headers=ADMIN)
            assert r.status_code == 200
            assert service.tilemap.version > version, "reset re-signals the tiles feed"
