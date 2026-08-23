"""Runtime configuration. Every knob is an env var; see docs/DEPLOY.md."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # access control — MUST be overridden for any internet-reachable deploy
    room_code: str = "classroom"
    admin_token: str = "change-me"

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

    @property
    def abs_state_dir(self) -> Path:
        return self.state_dir if self.state_dir.is_absolute() else SERVER_DIR / self.state_dir

    @property
    def abs_static_dir(self) -> Path:
        return self.static_dir if self.static_dir.is_absolute() else SERVER_DIR / self.static_dir
