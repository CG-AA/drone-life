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


def container_argv(s: Settings, student: Student, name: str, script_dir: Path) -> list[str]:
    return [
        "podman", "run", "--rm", "-i",
        "--name", name,
        "--label", "drone-life=1",
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
        s.runner_image,
        "python", "/work/current.py",
    ]
