"""The instructor console lives on its own loopback listener (ADMIN_PORT).

On the public port — the one the proxy and the classroom reach — /admin and
/api/v1/admin/* do not exist (404, not 403: nothing to probe). On the admin
listener they answer as before. ADMIN_PORT=0 puts the console back on the
public port, which is what the rest of the suite runs with.
"""

import socket

import httpx
import pytest

from .conftest import find_port_base, make_settings, running_app
from .test_ws import ws_session

ADMIN = {"X-Admin-Token": "test-admin"}
NOT_FOUND = {"error": {"code": "not_found", "msg": "not found"}}


async def test_console_answers_only_on_the_admin_listener(tmp_path):
    port = find_port_base(1)
    async with running_app(make_settings(tmp_path, admin_port=port)) as app:
        public = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                  base_url="http://test")
        async with public:
            r = await public.get("/api/v1/admin/students", headers=ADMIN)
            assert r.status_code == 404 and r.json() == NOT_FOUND
            assert (await public.get("/admin")).status_code == 404
            assert (await public.post("/api/v1/admin/reset", headers=ADMIN)).status_code == 404
            # everything else is untouched
            assert (await public.get("/healthz")).status_code == 200
            joined = await public.post("/api/v1/join",
                                       json={"room_code": "test-room", "name": "Ann"})
            assert joined.status_code == 200
        # the admin listener is a real socket on loopback
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as console:
            assert (await console.get("/api/v1/admin/students")).status_code == 403
            r = await console.get("/api/v1/admin/students", headers=ADMIN)
            assert r.status_code == 200
            assert [s["name"] for s in r.json()["students"]] == ["Ann"]
            info = await console.get("/api/v1/admin/info", headers=ADMIN)
            assert info.json()["admin_port"] == port
            assert (await console.get("/healthz")).status_code == 200
    # and the port is given back at shutdown
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    finally:
        sock.close()


async def test_a_console_websocket_path_on_the_public_side_is_closed_4404(tmp_path):
    port = find_port_base(1)
    async with running_app(make_settings(tmp_path, admin_port=port)) as app:
        sent = await ws_session(app, "/api/v1/admin/anything", "")
    assert [m["type"] for m in sent] == ["websocket.close"] and sent[0]["code"] == 4404


async def test_admin_port_zero_serves_the_console_on_the_public_port(tmp_path):
    async with running_app(make_settings(tmp_path, admin_port=0)) as app:
        public = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                  base_url="http://test")
        async with public:
            r = await public.get("/api/v1/admin/students", headers=ADMIN)
            assert r.status_code == 200


async def test_a_busy_admin_port_fails_the_boot_and_names_it(tmp_path):
    port = find_port_base(1)
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", port))
    squatter.listen()
    try:
        with pytest.raises(RuntimeError, match=f"ADMIN_PORT {port}"):
            async with running_app(make_settings(tmp_path, admin_port=port)):
                pass
    finally:
        squatter.close()
