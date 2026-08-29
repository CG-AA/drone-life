"""podman run argv for a student script — the whole sandbox policy in one place.

Rootless podman; slirp4netns with allow_host_loopback so the container reaches
the host's loopback-only MAVLink port at 10.0.2.2. The script directory is the
only mount (read-only, must be 0644 — host-owned files need to be world-readable
for the in-container non-root user through the uid mapping).
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..core.registry import Student

# the dronelife helper students import. The image bakes a copy at `make image`,
# but that copy goes stale the moment examples/dronelife.py changes (a rebuilt
# server with an old image = every script dies on import). Mounting the live
# file over the baked one, read-only, makes the image build-once for real.
HELPER = Path(__file__).resolve().parents[3] / "examples" / "dronelife.py"
HELPER_IN_IMAGE = "/usr/local/lib/python3.12/site-packages/dronelife.py"


def container_argv(s: Settings, student: Student, name: str, script_dir: Path) -> list[str]:
    return [
        "podman", "run", "--rm", "-i",
        "--name", name,
        # every room's container carries the first (`make kill-prod` sweeps on it);
        # a room's own sweep() keys on the second, so it never kills a neighbour's
        "--label", "drone-life=1",
        "--label", f"drone-life-room={s.room_id}",
        "--network", s.runner_network,
        "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
        "--read-only", "--tmpfs", "/tmp:rw,size=16m,mode=1777",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--security-opt", "label=disable",
        "--pull=never",
        "--env", f"DRONE_URL=tcp:{s.drone_host}:{student.port}",
        "--env", f"STUDENT_NAME={student.name}",
        "-v", f"{script_dir.resolve()}:/work:ro",
        "-v", f"{HELPER}:{HELPER_IN_IMAGE}:ro",
        s.runner_image,
        "python", "/work/current.py",
    ]
