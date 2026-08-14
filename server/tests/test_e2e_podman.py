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

from app.service import EXAMPLES_DIR
from tests.conftest import make_settings, running_app

pytestmark = pytest.mark.e2e


def image_available(image: str) -> bool:
    if shutil.which("podman") is None:
        return False
    return subprocess.run(["podman", "image", "exists", image],
                          capture_output=True).returncode == 0


async def test_container_courier_delivers(tmp_path):
    settings = make_settings(
        tmp_path,
        sim_unthrottled=False,  # real time: the container flies like a student's would
        room_code="e2e",
        admin_token="e2e-admin",
        max_students=3,
        sim_seed=11,
    )
    if not image_available(settings.runner_image):
        pytest.skip(f"podman or image {settings.runner_image} missing; run `make image`")

    async with running_app(settings) as app:
        service = app.state.service
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/v1/join",
                                  json={"room_code": "e2e", "name": "E2E-Courier"})
            assert r.status_code == 200, r.text
            token = r.json()["token"]
            student_id = r.json()["student_id"]
            auth = {"Authorization": f"Bearer {token}"}

            code = (EXAMPLES_DIR / "bot_courier.py").read_text()
            r = await client.post("/api/v1/submit", json={"code": code}, headers=auth)
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
                                  headers=auth)
            assert r.status_code == 200
            new_run_id = r.json()["run_id"]
            deadline = time.monotonic() + 45  # old-run kill grace alone can take 10s
            while time.monotonic() < deadline:
                run = service.runner.run_for(student_id)
                replaced_logs = "\n".join(
                    line["line"] for line in service.runner.log_for(student_id).tail(80))
                if run and run.run_id == new_run_id and "replaced" in replaced_logs:
                    break
                await asyncio.sleep(1)
            else:
                raise AssertionError(
                    f"replacement run never took over; logs:\n{replaced_logs}")
