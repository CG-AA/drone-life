"""The sandbox properties, checked from inside a real container.

test_podman_argv.py pins the flags we pass; this pins what they actually buy —
podman version changes, a stale image or a host that quietly ignores an option
would all pass the argv test and fail here.

Requires the built image:  make image   — then:  make e2e
"""

import asyncio
import time

import httpx
import pytest

from tests.conftest import make_settings, running_app
from tests.test_e2e_podman import image_available

pytestmark = pytest.mark.e2e

# Prints one PROBE <name>=OK/FAIL per property, then PROBE DONE. Deliberately
# plain: it must run on the image's bare python with no helper imports.
PROBE_SCRIPT = '''\
import os

def flag(name, ok):
    print("PROBE %s=%s" % (name, "OK" if ok else "FAIL"), flush=True)

def denied(path):
    """True when writing `path` is refused (the sandbox holding), else False."""
    try:
        open(path, "w").close()
        return False
    except OSError:
        return True

status = {}
with open("/proc/self/status") as fh:
    for line in fh:
        key, _, rest = line.partition(":")
        status[key] = rest.strip()

flag("capeff_zero", int(status["CapEff"], 16) == 0)
flag("no_new_privs", status["NoNewPrivs"] == "1")
flag("uid_nonroot", os.getuid() != 0)
flag("rootfs_readonly", denied("/probe"))
flag("script_mount_readonly", denied("/work/probe"))
flag("tmp_writable", not denied("/tmp/probe"))
flag("script_mode_644", (os.stat("/work/current.py").st_mode & 0o777) == 0o644)
print("PROBE DONE", flush=True)
'''

EXPECTED = [
    "capeff_zero",
    "no_new_privs",
    "uid_nonroot",
    "rootfs_readonly",
    "script_mount_readonly",
    "tmp_writable",
    "script_mode_644",
]


async def test_sandbox_properties_hold_inside_the_container(tmp_path):
    settings = make_settings(
        tmp_path,
        sim_unthrottled=False,
        room_code="e2e-probe",
        admin_token="e2e-admin",
        max_students=2,
        sim_seed=13,
    )
    if not image_available(settings.runner_image):
        pytest.skip(f"podman or image {settings.runner_image} missing; run `make image`")

    async with running_app(settings) as app:
        service = app.state.service
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            r = await client.post("/api/v1/join",
                                  json={"room_code": "e2e-probe", "name": "E2E-Probe"})
            assert r.status_code == 200, r.text
            student_id = r.json()["student_id"]
            auth = {"Authorization": f"Bearer {r.json()['token']}"}

            r = await client.post("/api/v1/submit", json={"code": PROBE_SCRIPT}, headers=auth)
            assert r.status_code == 200, r.text

            deadline = time.monotonic() + 60
            text = ""
            while time.monotonic() < deadline:
                tail = service.runner.log_for(student_id).tail(200)
                text = "\n".join(line["line"] for line in tail)
                if "PROBE DONE" in text:
                    break
                await asyncio.sleep(1)
            else:
                raise AssertionError(f"probe never finished within 60s; logs:\n{text}")

            assert "=FAIL" not in text, f"sandbox property broken:\n{text}"
            missing = [name for name in EXPECTED if f"PROBE {name}=OK" not in text]
            assert not missing, f"probe did not report {missing}; logs:\n{text}"
