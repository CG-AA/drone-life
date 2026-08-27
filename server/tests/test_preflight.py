"""Preflight: every failure must name the fix, and any FAIL must exit non-zero.

Podman is mocked throughout — this suite has to pass on boxes without it.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from app import preflight
from app.preflight import FAIL, PASS, WARN, Check

from .conftest import make_settings


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


def test_default_secrets_warn(tmp_path):
    defaults = make_settings(tmp_path, room_code="classroom", admin_token="change-me")
    check = preflight.check_defaults(defaults)
    assert check.status == WARN
    assert "ROOM_CODE" in check.detail and "ADMIN_TOKEN" in check.detail
    assert preflight.check_defaults(make_settings(tmp_path)).status == PASS


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
