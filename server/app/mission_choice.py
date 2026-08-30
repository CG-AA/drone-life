"""Which mission this room boots: the console's override file, else MISSION=.

The instructor switches missions from the console, which writes
`<STATE_DIR>/mission` and restarts the process (docs/DEPLOY.md, "Restarts and
mission switches"). The file wins over the environment at the next boot;
delete it (or "clear override" in the console) to hand the room back to
`MISSION=`. Per room by construction — it lives in the room's state dir — and
`make clean` takes it with everything else.

The snapshot is deliberately not the carrier: the snapshotter rewrites it
every 30 s with the *running* mission and would race the switch.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings
from .game.missions import MISSIONS

log = logging.getLogger(__name__)

OVERRIDE_NAME = "mission"


def override_path(settings: Settings) -> Path:
    return settings.abs_state_dir / OVERRIDE_NAME


def read_override(settings: Settings) -> str | None:
    """The override file's content, or None when there is none (or it is
    unreadable — the log says which)."""
    path = override_path(settings)
    try:
        value = path.read_text().strip()
    except FileNotFoundError:
        return None
    except OSError:
        log.exception("could not read %s", path)
        return None
    return value or None


def effective_mission(settings: Settings) -> tuple[str, str]:
    """(mission name, source) — source is "override" when the file decided,
    "env" otherwise. A file naming nothing is an error line, not a refusal:
    only the validated console route writes it, so a hand-typo blocking the
    8 am boot is the wrong trade; preflight names it too."""
    wanted = read_override(settings)
    if wanted is None:
        return settings.mission, "env"
    if wanted not in MISSIONS:
        log.error("%s names %r, which is not a mission (have %s) — ignoring it and booting "
                  "MISSION=%s", override_path(settings), wanted, ", ".join(sorted(MISSIONS)),
                  settings.mission)
        return settings.mission, "env"
    return wanted, "override"


def write_override(settings: Settings, mission: str) -> Path:
    if mission not in MISSIONS:
        raise ValueError(f"unknown mission {mission!r}; have {sorted(MISSIONS)}")
    path = override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mission + "\n")
    return path


def clear_override(settings: Settings) -> bool:
    """True if there was one to remove."""
    try:
        override_path(settings).unlink()
    except FileNotFoundError:
        return False
    return True
