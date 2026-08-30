"""Preflight: every failure must name the fix, and any FAIL must exit non-zero.

Podman is mocked throughout — this suite has to pass on boxes without it.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from app import preflight
from app.preflight import FAIL, PASS, WARN, Check

from .conftest import find_port_base, make_settings


def fake_podman(rc: int = 0, stderr: str = ""):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, rc, stdout="", stderr=stderr)
    return run


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


def test_missing_podman_fails_with_hint(settings, monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    check = preflight.check_podman(settings)
    assert check.status == FAIL
    assert "install podman" in check.detail


def test_missing_image_fails_with_make_image_hint(settings, monkeypatch):
    monkeypatch.setattr(preflight.subprocess, "run", fake_podman(rc=1))
    check = preflight.check_image(settings)
    assert check.status == FAIL
    assert "make image" in check.detail
    assert settings.runner_image in check.detail


def test_image_present_passes(settings, monkeypatch):
    monkeypatch.setattr(preflight.subprocess, "run", fake_podman(rc=0))
    assert preflight.check_image(settings).status == PASS


def test_subids_pass_and_fail(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(preflight.getpass, "getuser", lambda: "dronelife")
    good = tmp_path / "subuid"
    good.write_text("dronelife:100000:65536\n")
    assert preflight.check_subids(settings, good, good).status == PASS

    bad = tmp_path / "subuid-other"
    bad.write_text("someone-else:100000:65536\n")
    check = preflight.check_subids(settings, good, bad)
    assert check.status == FAIL
    assert "usermod --add-subuids" in check.detail
    assert "podman system migrate" in check.detail


def test_subids_unreadable_file_fails(settings, tmp_path):
    check = preflight.check_subids(settings, tmp_path / "nope", tmp_path / "nope")
    assert check.status == FAIL
    assert "unreadable" in check.detail


def test_slirp4netns_only_required_for_slirp_networks(settings, monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    assert preflight.check_slirp4netns(settings).status == FAIL

    bridged = make_settings(settings.abs_state_dir.parent, runner_network="none")
    assert preflight.check_slirp4netns(bridged).status == PASS


def test_busy_port_fails_and_names_it(settings, monkeypatch):
    monkeypatch.setattr(preflight, "server_running", lambda *a, **k: False)
    squatter = socket.socket()
    squatter.bind((settings.mavlink_host, settings.mavlink_base_port))
    try:
        check = preflight.check_ports(settings)
    finally:
        squatter.close()
    assert check.status == FAIL
    assert str(settings.mavlink_base_port) in check.detail
    assert "kill-prod" in check.detail


def test_free_ports_pass(settings, monkeypatch):
    monkeypatch.setattr(preflight, "server_running", lambda *a, **k: False)
    assert preflight.check_ports(settings).status == PASS


def test_ports_skipped_when_server_already_running(settings, monkeypatch):
    monkeypatch.setattr(preflight, "server_running", lambda *a, **k: True)
    check = preflight.check_ports(settings)
    assert check.status == WARN
    assert "server already up" in check.detail


def test_missing_web_dist_fails(settings, tmp_path):
    check = preflight.check_web_dist(make_settings(tmp_path, static_dir=tmp_path / "dist"))
    assert check.status == FAIL
    assert "make build" in check.detail


def test_built_web_dist_passes(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    for name in ("index.html", "submit.html", "admin.html"):
        (dist / name).write_text("<!doctype html>")
    assert preflight.check_web_dist(make_settings(tmp_path, static_dir=dist)).status == PASS


def test_state_dir_probe_and_corrupt_snapshot_warn(settings):
    assert preflight.check_state_dir(settings).status == PASS  # creates it

    (settings.abs_state_dir / "snapshot.json").write_text("{not json")
    check = preflight.check_state_dir(settings)
    assert check.status == WARN
    assert "corrupt" in check.detail

    (settings.abs_state_dir / "snapshot.json").write_text('{"students": [], "score": 0}')
    assert preflight.check_state_dir(settings).status == PASS


def test_default_secrets_fail_exactly_as_the_server_refuses_them(tmp_path):
    """preflight must never green-light a config the lifespan aborts on: the
    whole promise of `exit 1 means don't start class` rests on it."""
    defaults = make_settings(tmp_path, room_code="classroom", admin_token="change-me")
    check = preflight.check_defaults(defaults)
    assert check.status == FAIL
    assert "ROOM_CODE" in check.detail and "ADMIN_TOKEN" in check.detail
    assert preflight.check_defaults(make_settings(tmp_path)).status == PASS


def test_empty_secrets_fail_too(tmp_path):
    check = preflight.check_defaults(make_settings(tmp_path, room_code="   "))
    assert check.status == FAIL and "ROOM_CODE" in check.detail


def test_the_dev_escape_hatch_warns_instead_of_failing(tmp_path):
    check = preflight.check_defaults(make_settings(
        tmp_path, room_code="classroom", admin_token="change-me",
        allow_default_secrets=True))
    assert check.status == WARN and "ALLOW_DEFAULT_SECRETS" in check.detail


def test_an_unknown_mission_fails_before_the_server_refuses_to_boot(tmp_path):
    """MISSION is read at boot; the runbook has the operator hand-edit it right
    before a restart, so a typo must surface here, not in the journal."""
    check = preflight.check_mission(make_settings(tmp_path, mission="seige"))
    assert check.status == FAIL
    assert "seige" in check.detail and "siege" in check.detail
    assert preflight.check_mission(make_settings(tmp_path)).status == PASS


def test_the_override_file_decides_the_mission_and_a_typo_in_it_fails(tmp_path):
    """The console's switch writes <STATE_DIR>/mission; the boot follows it
    over MISSION=, so preflight must say so — and catch a bad one."""
    s = make_settings(tmp_path, mission="freefly")
    s.abs_state_dir.mkdir(parents=True)
    (s.abs_state_dir / "mission").write_text("siege\n")
    check = preflight.check_mission(s)
    assert check.status == PASS
    assert check.detail.startswith("siege") and "MISSION=freefly" in check.detail
    (s.abs_state_dir / "mission").write_text("seige\n")
    check = preflight.check_mission(s)
    assert check.status == FAIL and "seige" in check.detail and "delete the file" in check.detail


def test_admin_port_free_busy_or_off(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "server_running", lambda url: False)
    port = find_port_base(1)
    s = make_settings(tmp_path, admin_port=port)
    check = preflight.check_admin_port(s)
    assert check.status == PASS and f"ssh -L {port}:127.0.0.1:{port}" in check.detail
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", port))
    try:
        check = preflight.check_admin_port(s)
        assert check.status == FAIL and str(port) in check.detail and "8121+N" in check.detail
    finally:
        squatter.close()
    assert preflight.check_admin_port(make_settings(tmp_path, admin_port=0)).status == WARN
    monkeypatch.setattr(preflight, "server_running", lambda url: True)
    assert preflight.check_admin_port(s).status == WARN


def test_runtime_dir_uid_mismatch_fails(tmp_path, settings):
    """The bug that made every submit 503 'image not built': the unit's
    hardcoded uid did not match the service user's."""
    unit = tmp_path / "drone-life.service"
    unit.write_text("[Service]\nUser=root\nEnvironment=XDG_RUNTIME_DIR=/run/user/99999\n")
    check = preflight.check_runtime_dir(settings, unit=unit)
    assert check.status == FAIL
    assert "/run/user/0" in check.detail  # root is uid 0, whatever the unit says


def test_runtime_dir_without_the_setting_at_all_fails(tmp_path, settings):
    unit = tmp_path / "drone-life.service"
    unit.write_text("[Service]\nUser=root\n")
    check = preflight.check_runtime_dir(settings, unit=unit)
    assert check.status == FAIL and "XDG_RUNTIME_DIR" in check.detail


def test_runtime_dir_skipped_where_no_unit_is_installed(tmp_path, settings):
    check = preflight.check_runtime_dir(settings, unit=tmp_path / "nope.service")
    assert check.status == PASS


def test_runtime_dir_for_a_user_this_box_does_not_have_is_a_warning(tmp_path, settings):
    unit = tmp_path / "drone-life.service"
    unit.write_text("[Service]\nUser=nobody-here\nEnvironment=XDG_RUNTIME_DIR=/run/user/1\n")
    check = preflight.check_runtime_dir(settings, unit=unit)
    assert check.status == WARN


def test_proxy_header_warns_when_the_class_would_share_one_bucket(tmp_path, monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    prod = make_settings(tmp_path)
    assert preflight.check_proxy(prod).status == WARN
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.5")
    check = preflight.check_proxy(prod)
    assert check.status == PASS and "10.0.0.5" in check.detail


def test_proxy_header_is_not_a_dev_box_problem(tmp_path, monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    dev = make_settings(tmp_path, allow_default_secrets=True)
    assert preflight.check_proxy(dev).status == PASS


def test_smoke_run_reports_podman_stderr(settings, monkeypatch):
    monkeypatch.setattr(preflight.subprocess, "run",
                        fake_podman(rc=125, stderr="Error: image not known\n"))
    check = preflight.smoke_run(settings)
    assert check.status == FAIL
    assert "image not known" in check.detail


def test_smoke_run_passes(settings, monkeypatch):
    monkeypatch.setattr(preflight.subprocess, "run", fake_podman(rc=0))
    assert preflight.smoke_run(settings).status == PASS


def test_smoke_skipped_when_podman_or_image_failed(settings, monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    monkeypatch.setattr(preflight.subprocess, "run", fake_podman(rc=1))
    monkeypatch.setattr(preflight, "server_running", lambda *a, **k: False)
    smoke = preflight.collect(settings)[-1]
    assert smoke.name == "smoke run"
    assert smoke.status == WARN
    assert "fix the failures above" in smoke.detail


def test_run_exit_code_and_one_line_per_check(settings, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "collect",
                        lambda *a, **k: [Check("a", PASS, "fine"), Check("b", WARN, "meh")])
    assert preflight.run(settings) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(PASS) and out[1].startswith(WARN)
    assert "1 passed, 1 warned, 0 FAILED" in out[-1]

    monkeypatch.setattr(preflight, "collect", lambda *a, **k: [Check("a", FAIL, "broken")])
    assert preflight.run(settings) == 1
    assert "0 passed, 0 warned, 1 FAILED" in capsys.readouterr().out


# ------------------------------------------------------------------ rooms

def write_rooms(tmp_path, **rooms):
    d = tmp_path / "drone-life.d"
    d.mkdir(exist_ok=True)
    for name, body in rooms.items():
        (d / f"{name}.env").write_text(body)
    return d


def test_env_file_reads_like_systemd(tmp_path):
    f = tmp_path / "r1.env"
    f.write_text("# room 1\nPORT=8001\nROOM_LABEL=\"Room 1 — north\"\nMAX_STUDENTS=20 \n\nnoise\n")
    assert preflight.read_env_file(f) == {"PORT": "8001", "ROOM_LABEL": "Room 1 — north",
                                          "MAX_STUDENTS": "20"}


def test_room_env_overrides_the_shared_file(tmp_path):
    shared = tmp_path / "drone-life.env"
    shared.write_text("ROOM_CODE=abc\nMISSION=freefly\nPUBLIC_URL=https://h\n")
    room = tmp_path / "r2.env"
    room.write_text("PORT=8002\nPUBLIC_URL=https://h/r2\n")
    assert preflight.load_room_env(shared, room) == {
        "ROOM_CODE": "abc", "MISSION": "freefly", "PUBLIC_URL": "https://h/r2", "PORT": "8002"}
    assert preflight.load_room_env(tmp_path / "missing", room) == {"PORT": "8002", "PUBLIC_URL": "https://h/r2"}


def test_health_url_follows_the_room_port(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert preflight.health_url() == "http://127.0.0.1:8000/healthz"
    monkeypatch.setenv("PORT", "8003")
    assert preflight.health_url() == "http://127.0.0.1:8003/healthz"
    assert preflight.health_url(8001) == "http://127.0.0.1:8001/healthz"


GOOD_ROOMS = {
    "main": "PORT=8000\nMAVLINK_BASE_PORT=5760\nMAX_STUDENTS=64\nSTATE_DIR=state/main\n"
            "ADMIN_PORT=8121\n",
    "r1": "PORT=8001\nMAVLINK_BASE_PORT=5860\nMAX_STUDENTS=20\nSTATE_DIR=state/r1\n"
          "ADMIN_PORT=8122\n",
    "r2": "PORT=8002\nMAVLINK_BASE_PORT=5960\nMAX_STUDENTS=20\nSTATE_DIR=state/r2\n"
          "ADMIN_PORT=8123\n",
}


def parse(body):
    return dict(line.split("=", 1) for line in body.splitlines())


def test_room_plan_accepts_the_documented_layout():
    rooms = {k: parse(v) for k, v in GOOD_ROOMS.items()}
    assert preflight.room_plan(rooms, {"ROOM_CODE": "abc"}) == []


@pytest.mark.parametrize(("body", "needle"), [
    ("PORT=8003\nMAVLINK_BASE_PORT=5870\nMAX_STUDENTS=20\n",
     "overlap: r1 5860-5879 and r3 5870-5889"),
    ("PORT=8003\nMAVLINK_BASE_PORT=5800\nMAX_STUDENTS=20\n",
     "overlap: main 5760-5823 and r3 5800-5819"),
    ("PORT=8001\nMAVLINK_BASE_PORT=6060\n", "PORT 8001 is used by r1, r3"),
    ("MAVLINK_BASE_PORT=6060\n", "r3: no PORT"),
    ("PORT=8003\nMAVLINK_BASE_PORT=6060\nSTATE_DIR=state/r1\n",
     "STATE_DIR state/r1 is shared by r1, r3"),
    ("PORT=8003\nMAVLINK_BASE_PORT=6060\nROOM_CODE=other\n", "r3: its own ROOM_CODE differs"),
    # the console listener: a room file that says nothing gets 8121, main's
    ("PORT=8003\nMAVLINK_BASE_PORT=6060\n", "ADMIN_PORT 8121 is used by main, r3"),
    ("PORT=8003\nMAVLINK_BASE_PORT=6060\nADMIN_PORT=8122\n", "ADMIN_PORT 8122 is used by r1, r3"),
    ("PORT=8003\nMAVLINK_BASE_PORT=6060\nADMIN_PORT=8001\n",
     "ADMIN_PORT 8001 of r3 is also the PORT of r1"),
])
def test_room_plan_names_the_rooms_that_collide(body, needle):
    rooms = {k: parse(v) for k, v in GOOD_ROOMS.items()}
    rooms["r3"] = parse(body)
    problems = preflight.room_plan(rooms, {"ROOM_CODE": "abc"})
    assert any(needle in p for p in problems), problems


def test_check_room_plan_reads_the_files_and_names_each_room(settings, tmp_path):
    shared = tmp_path / "drone-life.env"
    shared.write_text("ROOM_CODE=abc\n")
    d = write_rooms(tmp_path, **GOOD_ROOMS)
    check = preflight.check_room_plan(settings, rooms_dir=d, shared=shared)
    assert check.status == PASS
    assert check.detail == "main:8000:5760-5823, r1:8001:5860-5879, r2:8002:5960-5979"

    (d / "r2.env").write_text("PORT=8001\nMAVLINK_BASE_PORT=5860\n")
    check = preflight.check_room_plan(settings, rooms_dir=d, shared=shared)
    assert check.status == FAIL
    assert "PORT 8001" in check.detail and "overlap" in check.detail


def test_check_room_plan_without_rooms_is_a_single_room(settings, tmp_path):
    assert preflight.check_room_plan(settings, rooms_dir=tmp_path / "nope").status == PASS
    empty = tmp_path / "empty"
    empty.mkdir()
    assert preflight.check_room_plan(settings, rooms_dir=empty).status == WARN


def test_room_ports_probe_each_room_on_its_own_port(settings, tmp_path, monkeypatch):
    base = settings.mavlink_base_port
    d = write_rooms(tmp_path, r1=f"PORT=8001\nMAVLINK_BASE_PORT={base}\nMAX_STUDENTS=2\n",
                    r2=f"PORT=8002\nMAVLINK_BASE_PORT={base + 2}\nMAX_STUDENTS=2\n")
    asked = []
    monkeypatch.setattr(preflight, "server_running", lambda url: asked.append(url) or False)
    checks = preflight.check_room_ports(settings, rooms_dir=d)
    assert [c.name for c in checks] == ["ports r1", "ports r2"]
    assert all(c.status == PASS for c in checks)
    assert asked == ["http://127.0.0.1:8001/healthz", "http://127.0.0.1:8002/healthz"]

    squatter = socket.socket()
    squatter.bind(("127.0.0.1", base + 2))
    try:
        checks = preflight.check_room_ports(settings, rooms_dir=d)
        assert checks[1].status == FAIL and str(base + 2) in checks[1].detail
    finally:
        squatter.close()


def test_runtime_dir_prefers_the_template_unit(tmp_path, settings, monkeypatch):
    monkeypatch.setattr(preflight.pwd, "getpwnam", lambda name: type("pw", (), {"pw_uid": 1234})())
    template = tmp_path / "drone-life@.service"
    template.write_text("[Service]\nUser=dronelife\nEnvironment=XDG_RUNTIME_DIR=/run/user/9\n")
    old = tmp_path / "drone-life.service"
    old.write_text("[Service]\nUser=dronelife\nEnvironment=XDG_RUNTIME_DIR=/run/user/1234\n")
    check = preflight.check_runtime_dir(settings, units=(template, old))
    assert check.status == FAIL and "drone-life@.service" in check.detail
    check = preflight.check_runtime_dir(settings, units=(tmp_path / "none", tmp_path / "none2"))
    assert check.status == PASS and "no none or none2" in check.detail
