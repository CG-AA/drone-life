"""The sandbox policy, pinned.

container_argv is the whole policy in one pure function, so every flag that
confines student code is asserted here. A loosening shows up as a failing unit
test in milliseconds rather than waiting for the podman-gated e2e suite.
"""

from app.core.registry import Student
from app.runner.podman import container_argv
from tests.conftest import make_settings


def build(tmp_path):
    settings = make_settings(tmp_path)
    student = Student(id="s0", name="Zoe", token="tok", slot=0, sysid=1, port=5760)
    return settings, student, container_argv(settings, student, "dl-s0-abc", tmp_path / "s0")


def value_of(argv, flag):
    """The argument following a flag (each of these appears once)."""
    return argv[argv.index(flag) + 1]


def test_runs_a_disposable_named_container(tmp_path):
    _, _, argv = build(tmp_path)
    assert argv[:4] == ["podman", "run", "--rm", "-i"]
    assert value_of(argv, "--name") == "dl-s0-abc"
    assert value_of(argv, "--label") == "drone-life=1"  # make kill-prod sweeps on this


def test_drops_every_capability(tmp_path):
    _, _, argv = build(tmp_path)
    assert value_of(argv, "--cap-drop") == "ALL"
    opts = [argv[i + 1] for i, a in enumerate(argv) if a == "--security-opt"]
    assert "no-new-privileges" in opts


def test_filesystem_is_read_only_except_tmp(tmp_path):
    _, _, argv = build(tmp_path)
    assert "--read-only" in argv
    assert value_of(argv, "--tmpfs") == "/tmp:rw,size=16m,mode=1777"


def test_resource_limits(tmp_path):
    _, _, argv = build(tmp_path)
    assert value_of(argv, "--memory") == "256m"
    assert value_of(argv, "--cpus") == "0.5"
    assert value_of(argv, "--pids-limit") == "64"


def test_the_live_helper_is_mounted_over_the_baked_copy(tmp_path):
    """examples/dronelife.py changes; the image does not. Every run must import
    the helper the server ships with, not whatever `make image` last saw."""
    from app.runner.podman import HELPER, HELPER_IN_IMAGE
    _, _, argv = build(tmp_path)
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert f"{HELPER}:{HELPER_IN_IMAGE}:ro" in mounts
    assert HELPER.is_file() and HELPER.name == "dronelife.py"
    assert HELPER_IN_IMAGE.endswith("/site-packages/dronelife.py")


def test_the_only_mounts_are_the_script_dir_and_the_helper_read_only(tmp_path):
    from app.runner.podman import HELPER, HELPER_IN_IMAGE
    _, _, argv = build(tmp_path)
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert mounts == [f"{(tmp_path / 's0').resolve()}:/work:ro",
                      f"{HELPER}:{HELPER_IN_IMAGE}:ro"]
    assert all(m.endswith(":ro") for m in mounts)


def test_never_pulls_at_run_time(tmp_path):
    """A submit must fail fast on a missing image, not reach for a registry."""
    _, _, argv = build(tmp_path)
    assert "--pull=never" in argv


def test_network_and_entrypoint(tmp_path):
    settings, student, argv = build(tmp_path)
    assert value_of(argv, "--network") == settings.runner_network
    envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
    assert f"DRONE_URL=tcp:{settings.drone_host}:{student.port}" in envs
    assert f"STUDENT_NAME={student.name}" in envs
    assert argv[-3:] == [settings.runner_image, "python", "/work/current.py"]
