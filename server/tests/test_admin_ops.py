"""Console operations: what the room is, switching the mission (an override
file plus a restart), and the ban list that survives a restart."""

import asyncio
import json

import httpx
import pytest

from app.game.missions import MISSIONS
from app.service import BOT_SCRIPTS, DroneLifeService

from .conftest import make_settings, running_app
from .test_ws import frames

ADMIN = {"X-Admin-Token": "test-admin"}


def client_for(app, ip: str = "10.0.0.5") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 1234)),
                             base_url="http://test")


async def hold_socket(app, path: str, query: str):
    """A student socket that stays open until the *server* closes it —
    ws_session() hangs up itself. Returns (task, sent frames)."""
    incoming: asyncio.Queue = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    sent: list[dict] = []

    async def receive() -> dict:
        return await incoming.get()

    async def send(message: dict) -> None:
        sent.append(message)
        if message["type"] == "websocket.close":
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    scope = {
        "type": "websocket", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "scheme": "ws", "path": path, "raw_path": path.encode(),
        "query_string": query.encode(), "root_path": "", "headers": [],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "subprotocols": [],
    }
    return asyncio.create_task(app(scope, receive, send)), sent


# ------------------------------------------------------------------- info

async def test_info_says_what_the_room_is_and_lists_the_dropdowns(tmp_path, monkeypatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    async with running_app(make_settings(tmp_path, room_label="North")) as app, \
            client_for(app) as c:
        assert (await c.get("/api/v1/admin/info")).status_code == 403
        body = (await c.get("/api/v1/admin/info", headers=ADMIN)).json()
    assert set(body) == {"room", "label", "mission", "mission_env", "mission_override",
                         "missions", "bot_scripts", "supervised", "admin_port", "uptime_s"}
    assert body["room"] == "main" and body["label"] == "North"
    assert body["mission"] == "delivery" == body["mission_env"]
    assert body["mission_override"] is None and body["supervised"] is False
    assert body["missions"] == sorted(MISSIONS) and body["bot_scripts"] == sorted(BOT_SCRIPTS)


# ---------------------------------------------------------------- restart

async def test_switching_writes_the_override_resets_the_round_and_leaves(tmp_path):
    settings = make_settings(tmp_path)
    override = settings.abs_state_dir / "mission"
    async with running_app(settings) as app:
        service: DroneLifeService = app.state.service
        left = asyncio.Event()
        service._exit = left.set
        async with client_for(app) as c:
            await c.post("/api/v1/join", json={"room_code": "test-room", "name": "Ann"})
            await service.join("Bot-1")
            service.engine.score = 7
            service.engine.scores["s0"] = 7
            bad = await c.post("/api/v1/admin/restart", json={"mission": "seige"}, headers=ADMIN)
            assert bad.status_code == 400 and "siege" in bad.json()["error"]["msg"]
            assert not override.exists() and not left.is_set()
            r = await c.post("/api/v1/admin/restart", json={"mission": "siege"}, headers=ADMIN)
            assert r.json() == {"restarting": True, "mission": "siege", "supervised": False}
            assert override.read_text().strip() == "siege"
            # the round is over: score zeroed, bots gone, humans kept
            assert service.engine.score == 0 and service.engine.scores == {}
            assert [s.name for s in service.registry.students.values()] == ["Ann"]
            kinds = [(e["kind"], e["msg"]) for e in service.bus.feed]
            assert ("restarting", "switching to siege — back in a few seconds") in kinds
            await asyncio.wait_for(left.wait(), 2)
            again = await c.post("/api/v1/admin/restart", json={}, headers=ADMIN)
            assert again.status_code == 409
        snap = json.loads((settings.abs_state_dir / "snapshot.json").read_text())
        assert snap["score"] == 0 and [s["name"] for s in snap["students"]] == ["Ann"]
    # the next boot follows the file, and says so in /info
    async with running_app(settings) as app:
        service = app.state.service
        assert service.engine.mission.name == "siege" and service.mission_source == "override"
        async with client_for(app) as c:
            info = (await c.get("/api/v1/admin/info", headers=ADMIN)).json()
            assert info["mission"] == "siege" and info["mission_override"] == "siege"
            assert info["mission_env"] == "delivery"
            cleared = await c.post("/api/v1/admin/mission/clear-override", headers=ADMIN)
            assert cleared.json() == {"cleared": True, "mission_env": "delivery"}
            assert not override.exists()
            assert (await c.post("/api/v1/admin/mission/clear-override",
                                 headers=ADMIN)).json()["cleared"] is False
    async with running_app(settings) as app:
        assert app.state.service.engine.mission.name == "delivery"


async def test_a_plain_restart_can_keep_the_score_and_touches_no_override(tmp_path):
    settings = make_settings(tmp_path)
    async with running_app(settings) as app:
        service: DroneLifeService = app.state.service
        service._exit = lambda: None
        service.engine.score = 5
        async with client_for(app) as c:
            r = await c.post("/api/v1/admin/restart", json={"keep_score": True}, headers=ADMIN)
            assert r.json()["mission"] == "delivery" and r.json()["restarting"] is True
        assert service.engine.score == 5
        assert not (settings.abs_state_dir / "mission").exists()
        assert [e["msg"] for e in service.bus.feed][-1] == \
            "server restarting — back in a few seconds"


def test_a_bad_override_file_falls_back_to_the_environment(tmp_path, caplog):
    settings = make_settings(tmp_path, mission="freefly")
    settings.abs_state_dir.mkdir(parents=True)
    (settings.abs_state_dir / "mission").write_text("seige\n")
    service = DroneLifeService(settings)
    assert service.engine.mission.name == "freefly" and service.mission_source == "env"
    assert "not a mission" in caplog.text and "seige" in caplog.text


def test_supervised_means_systemd_started_us(tmp_path, monkeypatch):
    service = DroneLifeService(make_settings(tmp_path))
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert service.supervised is False
    monkeypatch.setenv("INVOCATION_ID", "abc")
    assert service.supervised is True


# ------------------------------------------------------------------- bans

async def test_bans_by_hand_kick_now_persist_and_come_off_one_by_one(tmp_path):
    settings = make_settings(tmp_path)
    async with running_app(settings) as app, client_for(app, "10.0.0.5") as ann, \
            client_for(app, "10.0.0.6") as bob:
        token = (await ann.post("/api/v1/join", json={"room_code": "test-room",
                                                      "name": "Ann"})).json()["token"]
        await bob.post("/api/v1/join", json={"room_code": "test-room", "name": "Bob"})
        page, sent = await hold_socket(app, "/ws/student", f"token={token}")
        for _ in range(50):  # until the hello has gone out
            await asyncio.sleep(0)
            if any(f["type"] == "hello" for f in frames(sent)):
                break
        assert (await bob.post("/api/v1/admin/bans", json={}, headers=ADMIN)).status_code == 400
        # ban Ann's address by hand: she is kicked, her page's socket closes
        r = await bob.post("/api/v1/admin/bans", json={"ip": "10.0.0.5"}, headers=ADMIN)
        assert r.json() == {"kicked": ["Ann"]}
        await asyncio.wait_for(page, 2)
        assert sent[-1] == {"type": "websocket.close", "code": 4401, "reason": ""}
        assert (await ann.post("/api/v1/join", json={"room_code": "test-room",
                                                     "name": "Ann"})).status_code == 429
        # and a name nobody holds is just kept out
        r = await bob.post("/api/v1/admin/bans", json={"name": "Mallory"}, headers=ADMIN)
        assert r.json() == {"kicked": []}
        listed = (await bob.get("/api/v1/admin/bans", headers=ADMIN)).json()
        assert listed == {"names": ["mallory"], "ips": ["10.0.0.5"], "lockouts": []}
    # a restart keeps the list
    async with running_app(settings) as app, client_for(app, "10.0.0.6") as bob, \
            client_for(app, "10.0.0.5") as ann:
        listed = (await bob.get("/api/v1/admin/bans", headers=ADMIN)).json()
        assert listed["names"] == ["mallory"] and listed["ips"] == ["10.0.0.5"]
        assert (await ann.post("/api/v1/join", json={"room_code": "test-room",
                                                     "name": "Ann"})).status_code == 429
        mal = await bob.post("/api/v1/join", json={"room_code": "test-room",
                                                   "name": "mallory"})
        assert mal.status_code == 403 and mal.json()["error"]["code"] == "banned"
        assert (await bob.post("/api/v1/admin/bans/clear",
                               headers=ADMIN)).json() == {"unbanned": 2}
        assert (await ann.post("/api/v1/join", json={"room_code": "test-room",
                                                     "name": "Ann"})).status_code == 200


async def test_a_kicked_students_page_is_dropped_at_once(tmp_path):
    async with running_app(make_settings(tmp_path)) as app, client_for(app) as c:
        token = (await c.post("/api/v1/join", json={"room_code": "test-room",
                                                    "name": "Ann"})).json()["token"]
        page, sent = await hold_socket(app, "/ws/student", f"token={token}")
        for _ in range(50):
            await asyncio.sleep(0)
            if any(f["type"] == "hello" for f in frames(sent)):
                break
        assert (await c.post("/api/v1/admin/kick", json={"student_id": "s0"},
                             headers=ADMIN)).status_code == 200
        await asyncio.wait_for(page, 2)
        assert sent[-1]["type"] == "websocket.close" and sent[-1]["code"] == 4401
        assert app.state.hub.by_student.get("s0", set()) == set()


async def test_unlock_one_address(tmp_path):
    async with running_app(make_settings(tmp_path, join_strikes=1)) as app, \
            client_for(app, "10.0.0.9") as mal, client_for(app, "10.0.0.6") as bob:
        await mal.post("/api/v1/join", json={"room_code": "nope", "name": "M"})
        locked = (await bob.get("/api/v1/admin/bans", headers=ADMIN)).json()["lockouts"]
        assert [row["ip"] for row in locked] == ["10.0.0.9"]
        assert locked[0]["remaining_s"] == pytest.approx(900, abs=5)
        r = await bob.post("/api/v1/admin/unlock", json={"ip": "10.0.0.9"}, headers=ADMIN)
        assert r.json() == {"unlocked": 1}
        assert (await mal.post("/api/v1/join", json={"room_code": "test-room",
                                                     "name": "M"})).status_code == 200
