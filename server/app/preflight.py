"""Workshop-morning environment check: everything a submit needs, before a
student clicks Run. Reads the real Settings, so it checks the deploy you are
about to run — not a guess. `make preflight`; exit 1 means do not start class.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_ADMIN_TOKEN, DEFAULT_ROOM_CODE, Settings, check_secrets
from .game.missions import MISSIONS

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

HEALTH_URL = "http://127.0.0.1:8000/healthz"  # the port the Makefile and `main` room use
SMOKE_TIMEOUT = 30
MIN_FREE_BYTES = 1 << 30  # containers + logs + snapshot: a gig is plenty, less is a smell
# the template unit (rooms, docs/ROOMS.md) or the older single unit — whichever is installed
UNIT_PATHS = (Path("/etc/systemd/system/drone-life@.service"),
              Path("/etc/systemd/system/drone-life.service"))
UNIT_PATH = UNIT_PATHS[1]
# the shared env file and the per-room ones the template unit reads (docs/ROOMS.md)
ENV_FILE = Path("/etc/drone-life.env")
ROOMS_DIR = Path("/etc/drone-life.d")
# what a room file leaves unsaid: the Settings defaults, and the unit's STATE_DIR=state/%i
ROOM_DEFAULTS = {"MAVLINK_BASE_PORT": "5760", "MAX_STUDENTS": "20"}


def health_url(port: int | None = None) -> str:
    """This room's health endpoint. PORT is the unit's (and the runbook's) env
    var for the HTTP port, not a Settings field — uvicorn gets it on the CLI."""
    port = port or int(os.environ.get("PORT", "8000"))
    return f"http://127.0.0.1:{port}/healthz"


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
    except (OSError, subprocess.SubprocessError) as exc:
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


def check_ports(s: Settings, health: str | None = None, name: str = "mavlink ports") -> Check:
    """One MAVLink listener per student slot. A squatter here = joins 500."""
    health = health or health_url()
    if server_running(health):
        return Check(name, WARN, f"server already up on {health} — it owns these ports, skipped")
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
        return Check(name, FAIL,
                     f"in use: {', '.join(busy)} — `make kill-prod`, or `ss -ltnp` to find them")
    last = s.mavlink_base_port + s.max_students - 1
    return Check(name, PASS, f"{s.mavlink_base_port}-{last} free")


# ------------------------------------------------------------------ rooms

def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines the way systemd's EnvironmentFile reads them: blank lines
    and #-comments skipped, whitespace around the line ignored, one pair of
    surrounding quotes removed. Values are otherwise verbatim."""
    env: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[key.strip()] = value
    return env


def load_room_env(shared: Path, room: Path) -> dict[str, str]:
    """What the template unit gives instance `room`: the shared file, then the
    room's own on top — the same precedence as its two EnvironmentFile= lines."""
    env = read_env_file(shared) if shared.is_file() else {}
    env.update(read_env_file(room))
    return env


def room_files(rooms_dir: Path) -> dict[str, dict[str, str]]:
    return {p.stem: read_env_file(p) for p in sorted(rooms_dir.glob("*.env"))}


def room_plan(rooms: dict[str, dict[str, str]], shared: dict[str, str]) -> list[str]:
    """Why these room files cannot run side by side, or [] if they can. Pure,
    so the whole plan is a unit test: HTTP ports and state dirs must differ,
    MAVLink ranges must not overlap, and every room must share the classroom
    code (one code on every projector is the promise docs/ROOMS.md makes)."""
    problems: list[str] = []
    by_port: dict[str, list[str]] = {}
    by_state: dict[str, list[str]] = {}
    ranges: list[tuple[str, int, int]] = []
    for room, env in rooms.items():
        port = env.get("PORT")
        if not port:
            problems.append(f"{room}: no PORT — the unit passes it to uvicorn, so the room "
                            "would not start")
        else:
            by_port.setdefault(port, []).append(room)
        by_state.setdefault(env.get("STATE_DIR", f"state/{room}"), []).append(room)
        try:
            base = int(env.get("MAVLINK_BASE_PORT", ROOM_DEFAULTS["MAVLINK_BASE_PORT"]))
            seats = int(env.get("MAX_STUDENTS", ROOM_DEFAULTS["MAX_STUDENTS"]))
        except ValueError:
            problems.append(f"{room}: MAVLINK_BASE_PORT / MAX_STUDENTS are not numbers")
            continue
        ranges.append((room, base, base + seats - 1))
        code = env.get("ROOM_CODE")
        if code is not None and shared.get("ROOM_CODE") is not None \
                and code.strip() != shared["ROOM_CODE"].strip():
            problems.append(f"{room}: its own ROOM_CODE differs from the shared one — students "
                            "are told one code for every room")
    for port, names in by_port.items():
        if len(names) > 1:
            problems.append(f"PORT {port} is used by {', '.join(names)}")
    for state, names in by_state.items():
        if len(names) > 1:
            problems.append(f"STATE_DIR {state} is shared by {', '.join(names)} — their "
                            "rosters would overwrite each other")
    for i, (a, a0, a1) in enumerate(ranges):
        for b, b0, b1 in ranges[i + 1:]:
            if a0 <= b1 and b0 <= a1:
                problems.append(f"MAVLink ranges overlap: {a} {a0}-{a1} and {b} {b0}-{b1} — "
                                "room N is 5760+100N by convention")
    return problems


def check_room_plan(s: Settings, rooms_dir: Path = ROOMS_DIR, shared: Path = ENV_FILE) -> Check:
    """Every room file on the box, checked against each other — a room that
    passes on its own can still squat a neighbour's ports."""
    if not rooms_dir.is_dir():
        return Check("rooms", PASS, f"no {rooms_dir} — single room")
    rooms = room_files(rooms_dir)
    if not rooms:
        return Check("rooms", WARN, f"{rooms_dir} has no *.env — the template unit needs one per "
                                    "instance (docs/ROOMS.md)")
    problems = room_plan(rooms, read_env_file(shared) if shared.is_file() else {})
    if problems:
        return Check("rooms", FAIL, "; ".join(problems))
    summary = ", ".join(
        f"{room}:{env.get('PORT')}:{int(env.get('MAVLINK_BASE_PORT', 5760))}-"
        f"{int(env.get('MAVLINK_BASE_PORT', 5760)) + int(env.get('MAX_STUDENTS', 20)) - 1}"
        for room, env in rooms.items())
    return Check("rooms", PASS, summary)


def check_room_ports(s: Settings, rooms_dir: Path = ROOMS_DIR) -> list[Check]:
    """`--all-rooms`: are every room's MAVLink ports free (or owned by that
    room's running server)? One line per room."""
    checks = []
    for room, env in room_files(rooms_dir).items() if rooms_dir.is_dir() else []:
        try:
            base = env.get("MAVLINK_BASE_PORT", ROOM_DEFAULTS["MAVLINK_BASE_PORT"])
            seats = env.get("MAX_STUDENTS", ROOM_DEFAULTS["MAX_STUDENTS"])
            room_settings = Settings(mavlink_host=s.mavlink_host, mavlink_base_port=int(base),
                                     max_students=int(seats), allow_default_secrets=True)
            port = int(env.get("PORT", "0")) or None
        except ValueError as exc:
            checks.append(Check(f"ports {room}", FAIL, f"unreadable room file: {exc}"))
            continue
        checks.append(check_ports(room_settings, health_url(port), name=f"ports {room}"))
    return checks


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
    """The same call the lifespan makes — preflight must never green-light a
    config the server will refuse to boot on."""
    refusal = check_secrets(s)
    if refusal is not None:
        return Check("secrets", FAIL, refusal.removeprefix("refusing to start: "))
    weak = [name for name, value, default in
            (("ROOM_CODE", s.room_code, DEFAULT_ROOM_CODE),
             ("ADMIN_TOKEN", s.admin_token, DEFAULT_ADMIN_TOKEN))
            if not value or value == default]
    if weak:
        return Check("secrets", WARN,
                     f"{' and '.join(weak)} still default — booting only because "
                     "ALLOW_DEFAULT_SECRETS is set; dev only, never a room students reach")
    return Check("secrets", PASS, "overridden")


def check_mission(s: Settings) -> Check:
    """MISSION is read at boot and a typo aborts create_app — and the runbook
    has the operator hand-edit it right before a restart."""
    if s.mission not in MISSIONS:
        return Check("mission", FAIL,
                     f"MISSION={s.mission!r} is not a mission — the server would refuse to "
                     f"start; one of: {', '.join(sorted(MISSIONS))}")
    return Check("mission", PASS, s.mission)


def check_runtime_dir(s: Settings, unit: Path | None = None,
                      units: tuple[Path, ...] = UNIT_PATHS) -> Check:
    """Rootless podman needs XDG_RUNTIME_DIR and the unit hardcodes a uid.
    preflight runs from a login shell, where PAM sets the right one — so a green
    preflight is no proof the *service* can reach podman. Compare the unit's
    value against the uid of the unit's own User=, not whoever ran this.
    Reads the template unit if installed, else the old single one."""
    if unit is None:
        unit = next((u for u in units if u.is_file()), units[0])
    try:
        rows = [row.strip() for row in unit.read_text().splitlines()]
    except OSError:
        return Check("runtime dir", PASS,
                     f"no {' or '.join(u.name for u in units)} in {unit.parent} — this "
                     "shell's XDG_RUNTIME_DIR is not a service's; re-check after installing "
                     "the unit")
    declared = user = None
    for row in rows:
        if row.startswith("Environment=") and "XDG_RUNTIME_DIR=" in row:
            declared = row.split("XDG_RUNTIME_DIR=", 1)[1].strip().strip('"')
        elif row.startswith("User="):
            user = row.split("=", 1)[1].strip()
    if user is None:
        return Check("runtime dir", WARN, f"{unit} names no User= — cannot check its uid")
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return Check("runtime dir", WARN,
                     f"{unit} runs as {user!r}, who does not exist here — check on the "
                     "lab server, where it does")
    want = f"/run/user/{uid}"
    if declared is None:
        return Check("runtime dir", FAIL,
                     f"{unit} sets no XDG_RUNTIME_DIR — rootless podman needs it; add "
                     f"`Environment=XDG_RUNTIME_DIR={want}`")
    if declared != want:
        return Check("runtime dir", FAIL,
                     f"{unit} says {declared} but {user} is uid {uid} — every submit would "
                     f"503 'runner image is not built'; set it to {want}")
    if not Path(declared).is_dir():
        return Check("runtime dir", FAIL,
                     f"{declared} does not exist — `sudo loginctl enable-linger {user}`")
    return Check("runtime dir", PASS, f"{declared} (uid of {user})")


def check_proxy(s: Settings) -> Check:
    """uvicorn reads FORWARDED_ALLOW_IPS itself (not config.py). Without it every
    student behind the proxy shares one join bucket, so 30 wrong codes lock out
    the class — and the projector with them."""
    value = os.environ.get("FORWARDED_ALLOW_IPS", "").strip()
    if value:
        return Check("proxy header", PASS, f"X-Forwarded-For believed from {value}")
    if s.allow_default_secrets:
        return Check("proxy header", PASS, "dev box (ALLOW_DEFAULT_SECRETS) — no proxy")
    return Check("proxy header", WARN,
                 "FORWARDED_ALLOW_IPS unset — behind the proxy the whole class shares one "
                 "join bucket; set it in /etc/drone-life.env to the proxy's address")


def smoke_run(s: Settings) -> Check:
    """The only check that proves uid mapping, network and image python agree."""
    argv = ["run", "--rm", "--network", s.runner_network, "--pull=never",
            s.runner_image, "python", "-c", "print('ok')"]
    try:
        proc = _podman(*argv, timeout=SMOKE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return Check("smoke run", FAIL, f"container did not finish in {SMOKE_TIMEOUT}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("smoke run", FAIL, f"could not run podman: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return Check("smoke run", FAIL,
                     f"exit {proc.returncode}: {err[-1] if err else 'no output'}")
    return Check("smoke run", PASS, "container ran and exited 0")


def collect(s: Settings, *, smoke: bool = True, all_rooms: bool = False) -> list[Check]:
    checks = [check_podman(s), check_image(s), check_subids(s), check_slirp4netns(s),
              check_ports(s), check_web_dist(s), check_state_dir(s), check_disk(s),
              check_defaults(s), check_mission(s), check_runtime_dir(s), check_proxy(s),
              check_room_plan(s)]
    if all_rooms:
        checks.extend(check_room_ports(s))
    if not smoke:
        return checks
    blocked = [c for c in checks[:2] if c.status == FAIL]  # podman + image
    if blocked:
        checks.append(Check("smoke run", WARN, "skipped — fix the failures above first"))
    else:
        checks.append(smoke_run(s))
    return checks


def run(s: Settings, *, smoke: bool = True, all_rooms: bool = False) -> int:
    checks = collect(s, smoke=smoke, all_rooms=all_rooms)
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
    parser.add_argument("--room", metavar="ID",
                        help=f"check instance ID the way its unit sees it: {ENV_FILE} then "
                             f"{ROOMS_DIR}/ID.env are loaded over this shell's environment")
    parser.add_argument("--all-rooms", action="store_true",
                        help=f"also probe every room in {ROOMS_DIR} for free MAVLink ports")
    args = parser.parse_args()
    if args.room:
        room_file = ROOMS_DIR / f"{args.room}.env"
        if not room_file.is_file():
            sys.exit(f"preflight: no {room_file} — every instance needs one (docs/ROOMS.md)")
        os.environ.update(load_room_env(ENV_FILE, room_file))
        os.environ["ROOM_ID"] = args.room
    sys.exit(run(Settings(), smoke=not args.no_smoke, all_rooms=args.all_rooms))


if __name__ == "__main__":
    main()
