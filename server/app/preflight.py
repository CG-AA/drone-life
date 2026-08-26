"""Workshop-morning environment check: everything a submit needs, before a
student clicks Run. Reads the real Settings, so it checks the deploy you are
about to run — not a guess. `make preflight`; exit 1 means do not start class.
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

HEALTH_URL = "http://127.0.0.1:8000/healthz"  # the port the Makefile and unit both use
SMOKE_TIMEOUT = 30
MIN_FREE_BYTES = 1 << 30  # containers + logs + snapshot: a gig is plenty, less is a smell


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""

    def line(self) -> str:
        return f"{self.status}  {self.name:<14}{self.detail}".rstrip()


def _podman(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(["podman", *args], capture_output=True, text=True, timeout=timeout)


def check_podman(s: Settings) -> Check:
    path = shutil.which("podman")
    if path is None:
        return Check("podman", FAIL, "not on PATH — install podman (student sandbox needs it)")
    return Check("podman", PASS, path)


def check_image(s: Settings) -> Check:
    try:
        rc = _podman("image", "exists", s.runner_image).returncode
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return Check("runner image", FAIL, f"could not ask podman: {exc}")
    if rc != 0:
        return Check("runner image", FAIL, f"{s.runner_image} missing — run `make image`")
    return Check("runner image", PASS, s.runner_image)


def check_subids(s: Settings, subuid: Path = Path("/etc/subuid"),
                 subgid: Path = Path("/etc/subgid")) -> Check:
    """Rootless podman maps the container's uid range out of these files."""
    user = getpass.getuser()
    missing = []
    for path in (subuid, subgid):
        try:
            rows = path.read_text().splitlines()
        except OSError:
            missing.append(f"{path} unreadable")
            continue
        if not any(row.split(":")[0] == user for row in rows):
            missing.append(f"no {user} range in {path}")
    if missing:
        return Check("subuid/subgid", FAIL,
                     f"{'; '.join(missing)} — `sudo usermod --add-subuids 100000-165535 "
                     f"--add-subgids 100000-165535 {user}` then `podman system migrate`")
    return Check("subuid/subgid", PASS, f"{user} mapped")


def check_slirp4netns(s: Settings) -> Check:
    if not s.runner_network.startswith("slirp4netns"):
        return Check("slirp4netns", PASS, f"not needed for network {s.runner_network!r}")
    path = shutil.which("slirp4netns")
    if path is None:
        return Check("slirp4netns", FAIL,
                     "missing — containers cannot reach the drone ports; install slirp4netns")
    return Check("slirp4netns", PASS, path)


def server_running(url: str = HEALTH_URL) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except (urllib.error.URLError, OSError):
        return False


def check_ports(s: Settings) -> Check:
    """One MAVLink listener per student slot. A squatter here = joins 500."""
    if server_running():
        return Check("mavlink ports", WARN, "server already up — it owns these ports, skipped")
    busy = []
    for i in range(s.max_students):
        port = s.mavlink_base_port + i
        sock = socket.socket()
        try:
            sock.bind((s.mavlink_host, port))
        except OSError:
            busy.append(str(port))
        finally:
            sock.close()
    if busy:
        return Check("mavlink ports", FAIL,
                     f"in use: {', '.join(busy)} — `make kill-prod`, or `ss -ltnp` to find them")
    last = s.mavlink_base_port + s.max_students - 1
    return Check("mavlink ports", PASS, f"{s.mavlink_base_port}-{last} free")


def check_web_dist(s: Settings) -> Check:
    dist = s.abs_static_dir.resolve()
    wanted = ["index.html", "submit.html", "admin.html"]
    missing = [name for name in wanted if not (dist / name).is_file()]
    if missing:
        return Check("web build", FAIL, f"{dist} missing {', '.join(missing)} — run `make build`")
    return Check("web build", PASS, str(dist))


def check_state_dir(s: Settings) -> Check:
    state = s.abs_state_dir
    try:
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".preflight"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        return Check("state dir", FAIL, f"{state} not writable: {exc}")
    snap = state / "snapshot.json"
    if snap.exists():
        try:
            json.loads(snap.read_text())
        except (OSError, json.JSONDecodeError):
            return Check("state dir", WARN,
                         f"{snap} is corrupt — delete it (roster and tokens are lost)")
    return Check("state dir", PASS, str(state))


def check_disk(s: Settings) -> Check:
    try:
        free = shutil.disk_usage(s.abs_state_dir).free
    except OSError as exc:
        return Check("disk space", WARN, f"could not measure: {exc}")
    gib = free / (1 << 30)
    if free < MIN_FREE_BYTES:
        return Check("disk space", WARN, f"{gib:.1f} GiB free — thin for container layers + logs")
    return Check("disk space", PASS, f"{gib:.1f} GiB free")


def check_defaults(s: Settings) -> Check:
    weak = []
    if s.room_code == "classroom":
        weak.append("ROOM_CODE")
    if s.admin_token == "change-me":
        weak.append("ADMIN_TOKEN")
    if weak:
        return Check("secrets", WARN,
                     f"{' and '.join(weak)} still default — fine on a closed lab net, "
                     "not for anything reachable")
    return Check("secrets", PASS, "overridden")


def smoke_run(s: Settings) -> Check:
    """The only check that proves uid mapping, network and image python agree."""
    argv = ["run", "--rm", "--network", s.runner_network, "--pull=never",
            s.runner_image, "python", "-c", "print('ok')"]
    try:
        proc = _podman(*argv, timeout=SMOKE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return Check("smoke run", FAIL, f"container did not finish in {SMOKE_TIMEOUT}s")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return Check("smoke run", FAIL, f"could not run podman: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return Check("smoke run", FAIL,
                     f"exit {proc.returncode}: {err[-1] if err else 'no output'}")
    return Check("smoke run", PASS, "container ran and exited 0")


def collect(s: Settings, *, smoke: bool = True) -> list[Check]:
    checks = [check_podman(s), check_image(s), check_subids(s), check_slirp4netns(s),
              check_ports(s), check_web_dist(s), check_state_dir(s), check_disk(s),
              check_defaults(s)]
    if not smoke:
        return checks
    blocked = [c for c in checks[:2] if c.status == FAIL]  # podman + image
    if blocked:
        checks.append(Check("smoke run", WARN, "skipped — fix the failures above first"))
    else:
        checks.append(smoke_run(s))
    return checks


def run(s: Settings, *, smoke: bool = True) -> int:
    checks = collect(s, smoke=smoke)
    for check in checks:
        print(check.line())
    failed = sum(c.status == FAIL for c in checks)
    warned = sum(c.status == WARN for c in checks)
    passed = sum(c.status == PASS for c in checks)
    print(f"\npreflight: {passed} passed, {warned} warned, {failed} FAILED")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="check this box can run a workshop")
    parser.add_argument("--no-smoke", action="store_true",
                        help="skip the test container run (faster, less thorough)")
    args = parser.parse_args()
    sys.exit(run(Settings(), smoke=not args.no_smoke))


if __name__ == "__main__":
    main()
