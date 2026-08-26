"""Runtime configuration. Every knob is an env var; see docs/DEPLOY.md."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[1]

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
    sim_seed: int = 42
    sim_unthrottled: bool = False  # tests: run the driver without sleeping

    runner_image: str = "drone-life-runner:latest"
    runner_network: str = "slirp4netns:allow_host_loopback=true"
    drone_host: str = "10.0.2.2"  # host loopback as seen from inside a container
    run_max_seconds: int = 900

    state_dir: Path = Path("state")
    static_dir: Path = Path("../web/dist")

    join_rate_limit_per_minute: int = 30  # per IP, guards room-code guessing
    submit_rate_limit_per_minute: int = 10  # per student, guards container churn

    @property
    def abs_state_dir(self) -> Path:
        return self.state_dir if self.state_dir.is_absolute() else SERVER_DIR / self.state_dir

    @property
    def abs_static_dir(self) -> Path:
        return self.static_dir if self.static_dir.is_absolute() else SERVER_DIR / self.static_dir


def check_secrets(settings: Settings) -> str | None:
    """Refusal message when the access-control secrets are placeholders, else None.

    Empty is worse than the default: a blank ROOM_CODE matches a blank submission,
    so anyone gets in. Called from the lifespan — see main.py.
    """
    bad = []
    if not settings.room_code.strip() or settings.room_code == DEFAULT_ROOM_CODE:
        bad.append("ROOM_CODE")
    if not settings.admin_token.strip() or settings.admin_token == DEFAULT_ADMIN_TOKEN:
        bad.append("ADMIN_TOKEN")
    if not bad or settings.allow_default_secrets:
        return None
    return (
        f"refusing to start: default or empty {' and '.join(bad)} — set real values "
        "in the environment, or ALLOW_DEFAULT_SECRETS=1 for local dev"
    )
