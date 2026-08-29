"""Runtime configuration. Every knob is an env var; see docs/DEPLOY.md."""

import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[1]

# a room id is a systemd instance name, a podman label value and a state-dir
# segment at once — keep it to what all three accept without quoting
ROOM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# placeholders the startup guard refuses to run on — see check_secrets()
DEFAULT_ROOM_CODE = "classroom"
DEFAULT_ADMIN_TOKEN = "change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # access control — MUST be overridden for any internet-reachable deploy
    room_code: str = DEFAULT_ROOM_CODE
    admin_token: str = DEFAULT_ADMIN_TOKEN
    allow_default_secrets: bool = False  # dev only: boot anyway on the placeholders

    # (the HTTP bind address/port are uvicorn CLI flags — see the Makefile)

    # MAVLink endpoints stay on loopback; containers reach them via slirp host-loopback
    mavlink_host: str = "127.0.0.1"
    mavlink_base_port: int = 5760

    max_students: int = 20
    mission: str = "delivery"
    # rooms (docs/ROOMS.md): the small missions run as several processes behind
    # the proxy on /r1, /r2, …; the big room stays at /. ROOM_ID names this
    # process (the systemd instance), ROOMS lists the small rooms the student
    # page offers, ROOM_LABEL is what that list calls this room.
    room_id: str = "main"
    room_label: str = ""
    rooms: str = ""  # ROOMS=r1,r2,r3 — ids; each is served at /<id>/
    # what the projector's "join the sky at" card shows: the address students
    # can actually reach (the public gateway), which is rarely the address the
    # projector page itself was opened on. Empty = the page's own origin.
    public_url: str = ""
    sim_seed: int = 42
    sim_unthrottled: bool = False  # tests: run the driver without sleeping
    # dev only: more scripts the admin console may spawn as bots, by path
    # under examples/ without ".py" — EXTRA_BOT_SCRIPTS=answers/quest_route,…
    # (the worked answers stay out of the template menu and the default
    # allowlist so a class never sees them before the wrap)
    extra_bot_scripts: str = ""

    runner_image: str = "drone-life-runner:latest"
    runner_network: str = "slirp4netns:allow_host_loopback=true"
    drone_host: str = "10.0.2.2"  # host loopback as seen from inside a container
    run_max_seconds: int = 900

    state_dir: Path = Path("state")
    static_dir: Path = Path("../web/dist")

    join_rate_limit_per_minute: int = 30  # per IP, guards room-code guessing
    join_strikes: int = 3  # wrong room codes per IP before a lockout (0 = off)
    join_lockout_s: int = 900  # how long the lockout lasts (0 = until restart)
    submit_rate_limit_per_minute: int = 10  # per student, guards container churn

    @field_validator("room_code", "admin_token")
    @classmethod
    def _strip_secret(cls, v: str) -> str:
        """A systemd EnvironmentFile does not trim, and every client-side compare
        strips what the browser sent — so `ROOM_CODE=abc ` would 403 the whole
        class while the startup guard and preflight both saw a real value."""
        return v.strip()

    @field_validator("room_id")
    @classmethod
    def _room_id_is_a_name(cls, v: str) -> str:
        v = v.strip()
        if not ROOM_ID_RE.match(v):
            raise ValueError(f"ROOM_ID={v!r} — use lowercase letters, digits, '-' or '_' "
                             "(it names a systemd instance, a podman label and a state dir)")
        return v

    @property
    def room_list(self) -> list[str]:
        """ROOMS as ids, in the order the student page lists them."""
        return [r for r in (x.strip() for x in self.rooms.split(",")) if r]

    @property
    def abs_state_dir(self) -> Path:
        return self.state_dir if self.state_dir.is_absolute() else SERVER_DIR / self.state_dir

    @property
    def abs_static_dir(self) -> Path:
        return self.static_dir if self.static_dir.is_absolute() else SERVER_DIR / self.static_dir


def check_secrets(settings: Settings) -> str | None:
    """Refusal message when the access-control secrets are placeholders, else None.

    Empty is worse than the default: a blank ROOM_CODE matches a blank submission,
    so anyone gets in (Settings strips both, so whitespace is empty). Called from
    the lifespan — see main.py, and from preflight so both agree.
    """
    bad = []
    if not settings.room_code or settings.room_code == DEFAULT_ROOM_CODE:
        bad.append("ROOM_CODE")
    if not settings.admin_token or settings.admin_token == DEFAULT_ADMIN_TOKEN:
        bad.append("ADMIN_TOKEN")
    if not bad or settings.allow_default_secrets:
        return None
    return (
        f"refusing to start: default or empty {' and '.join(bad)} — set real values "
        "in the environment, or ALLOW_DEFAULT_SECRETS=1 for local dev"
    )
