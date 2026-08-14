"""End-to-end: bot_courier.py submitted through the real REST endpoint, run in a
real rootless podman container, reaching the sim through slirp host-loopback,
completing a delivery. If this passes, a student's browser flow works too.

Requires the built image:  make image   — then:  make e2e
"""

import asyncio
import shutil
import subprocess
import time

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.service import EXAMPLES_DIR
from tests.conftest import find_port_base

pytestmark = pytest.mark.e2e

IMAGE = "drone-life-runner:latest"


def image_available() -> bool:
    if shutil.which("podman") is None:
        return False
    return subprocess.run(["podman", "image", "exists", IMAGE],
                          capture_output=True).returncode == 0


async def test_container_courier_delivers(tmp_path):
    if not image_available():
        pytest.skip(f"podman or image {IMAGE} not available; run `make image`")

    settings = Settings(
        sim_unthrottled=False,  # real time: the container flies like a student's would
        mavlink_base_port=find_port_base(),
        state_dir=tmp_path / "state",
        room_code="e2e",
        admin_token="e2e-admin",
        max_students=3,
        sim_seed=11,
    )
    app = create_app(settings)
    service = app.state.service
    await service.start()
    app.state.hub.start()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/v1/join",
                                  json={"room_code": "e2e", "name": "E2E-Courier"})
            assert r.status_code == 200, r.text
            token = r.json()["token"]
            student_id = r.json()["student_id"]

            code = (EXAMPLES_DIR / "bot_courier.py").read_text()
            r = await client.post("/api/v1/submit", json={"code": code},
                                  headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200, r.text

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and service.engine.score == 0:
                await asyncio.sleep(1)

            tail = service.runner.log_for(student_id).tail(200)
            log_text = "\n".join(line["line"] for line in tail)
            assert service.engine.score >= 10, (
                f"no delivery within 120s; logs:\n{log_text}")
            # the log pipeline carried the container's stdout
            assert "took off" in log_text or "connected" in log_text

            # resubmit mid-flight must replace the run cleanly
            r = await client.post("/api/v1/submit", json={"code": "print('replaced')"},
                                  headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            await asyncio.sleep(8)
            run = service.runner.run_for(student_id)
            assert run is not None and run.state in ("running", "exited")
            replaced_logs = "\n".join(
                line["line"] for line in service.runner.log_for(student_id).tail(50))
            assert "replaced" in replaced_logs
    finally:
        await app.state.hub.stop()
        await service.stop()
