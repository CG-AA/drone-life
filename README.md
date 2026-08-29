# drone life

A one-day-workshop co-op drone game. Students write **pymavlink** scripts in
the browser; each script flies a simulated drone in one shared 200×200 m arena,
rendered live on a projector-friendly **2.5D isometric viewer**. The day has an
arc: `freefly` warms up (the unedited template is a visible win), `delivery`
teaches the GAME-message loop and co-op scoring, and **`siege` is the main
event** — three rounds of tower defense against creeps marching on the Keep.

```
students' browsers ──▶ submit page ──▶ podman sandbox ──▶ MAVLink/TCP ─┐
                                                                       ▼
projector ◀── WebSocket ◀── FastAPI ◀── game engine ◀── 20 Hz kinematic sim
```

One Python process (FastAPI + asyncio) hosts the sim, per-drone MAVLink TCP
endpoints (loopback only), the mission engine, the podman script runner and the
web/WS API on **one HTTP port**. Scripts are real pymavlink against ArduPilot
GUIDED-mode conventions — the skills transfer to real drones.

**Running a workshop?** Jump to [Run a workshop](#run-a-workshop).

## What you need

| tool | why | version |
|---|---|---|
| git, make, curl | clone, drive everything, fetch installers | any |
| uv | Python 3.12 + server deps, no system Python juggling | any recent |
| Node + npm | build the web viewer once (`web/dist`) | **Node 22** (`>=20` required) |
| podman + uidmap + slirp4netns | the rootless student-script sandbox | podman 4.x (Ubuntu 24.04's) |

Everything below assumes a **normal user with sudo, not root** — rootless
podman keeps its image store per user. Ubuntu 24.04, one paste:

```bash
sudo apt update && sudo apt install -y git make curl openssl podman uidmap slirp4netns
curl -LsSf https://astral.sh/uv/install.sh | sh && . ~/.local/bin/env
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
git --version && uv --version && node --version && npm --version && podman --version
```

- Apt's own `nodejs` package is **18.x**: it installs fine and then fails at
  `npm run build`. Use the NodeSource line above (or nvm with `web/.nvmrc`).
- podman is only needed for the student sandbox (`make image`, real submits,
  `make e2e`). The viewer, the dev server and bots in `MODE=local` work
  without it.
- Only root on the box (fresh VM/container)? Make a user first:
  `adduser --disabled-password --gecos "" pilot && echo 'pilot ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/pilot && su - pilot`

## Try it in 5 minutes

```bash
git clone https://github.com/CG-AA/drone-life.git && cd drone-life
cd server && uv sync && cd ..                 # Python 3.12 + deps into server/.venv
cd web && npm ci && npm run build && cd ..    # → web/dist, served by the server
make dev-server                               # http://localhost:8000  (Ctrl-C stops it)
```

In a second terminal: `cd drone-life && make bots N=5 ADMIN_TOKEN=change-me` —
five demo drones patrol on the viewer.

- `http://localhost:8000/` — the projector view; room code `classroom`
- `http://localhost:8000/submit` — what students see: editor, Run, live log
- `http://localhost:8000/admin` — instructor console; token `change-me`

Those placeholder secrets only boot because `make dev-server` passes
`ALLOW_DEFAULT_SECRETS=1`; any other launch refuses to start until you set
real ones (`ROOM_CODE`, `ADMIN_TOKEN`).

Now the path a student's script really takes — a rootless podman container:

```bash
make image                                    # builds drone-life-runner:latest (pulls python:3.12-slim once)
ALLOW_DEFAULT_SECRETS=1 make preflight        # can this box run a class? 0 FAILED is the bar
```

`make preflight` checks podman, the runner image, subuid/subgid ranges,
slirp4netns, the 20 MAVLink ports, `web/dist`, the state dir, disk, the
secrets (placeholders FAIL unless `ALLOW_DEFAULT_SECRETS`), `XDG_RUNTIME_DIR`,
and then runs one real container. Every FAIL line names its fix. Then open
`/submit`, join with `classroom`, press **Run** on the unedited template: the
drone climbs and moves on the projector view.

## Run a workshop

### Pick a deployment

**A. One box on the room's wifi** (simplest, no proxy). Same box for the
server and the projector; students only need a browser on the same network.

```bash
cd drone-life
make image                                    # once per box (and per user: rootless image store)
sudo tee /etc/drone-life.env >/dev/null <<EOF
ROOM_CODE=$(openssl rand -hex 4)
ADMIN_TOKEN=$(openssl rand -base64 24)
MISSION=freefly
EOF
sudo chown "$USER" /etc/drone-life.env && sudo chmod 600 /etc/drone-life.env
cat /etc/drone-life.env                       # ROOM_CODE goes on the projector; ADMIN_TOKEN stays with you
set -a && . /etc/drone-life.env && set +a && make preflight   # 0 FAILED?
set -a && . /etc/drone-life.env && set +a && make run         # binds 0.0.0.0:8000; leave this terminal open
make reset                                    # (second terminal) the first `make run` restores whatever
                                              # server/state holds — the demo bots from *Try it* included
```

`make run` refuses placeholder secrets by design; `make` does not read the
env file by itself, hence the `set -a && . … && set +a` prefix (use it in
every terminal where you run `make preflight` / `bots` / `reset`). Then:

- Students: `http://<box-ip>:8000/submit` + the room code
  (`hostname -I | awk '{print $1}'` prints the box IP). Projector:
  `http://<box-ip>:8000/`, room code entered once.
- Firewall: open **only** TCP 8000 (`sudo ufw allow 8000/tcp` if ufw is on);
  MAVLink stays on loopback by construction.
- To survive a logout or reboot, run it under systemd instead of a terminal:
  [DEPLOY.md → systemd](docs/DEPLOY.md#systemd) (that doc's `/opt/drone-life`
  + `dronelife` user layout).

**B. Lab server behind a reverse proxy / gateway** (internet-reachable,
TLS, a NAT'd lab box): [docs/DEPLOY.md](docs/DEPLOY.md), including the
optional SSH reverse tunnel in
[docs/deploy/gateway-tunnel/](docs/deploy/gateway-tunnel/README.md).

### Day −1 checklist

- Env-sourced `make preflight` on the **actual** box: 0 FAILED, smoke container included.
- `make image` then `make e2e`: one real container delivers a crate (without
  the image the suite *skips*, it does not fail).
- `make load LOAD_BOTS=20` on the actual hardware; overruns < 1% on `/healthz`.
- Rehearse one mission switch (edit `MISSION`, restart, `make reset`); time it.
- Printed `docs/CHEATSHEET.md` per seat; projector readable from 5 m; one phone joins over the room wifi.

Full list: [SESSION_PLAN.md → Day −1 checklist](docs/SESSION_PLAN.md#day-1-checklist-cannot-be-verified-off-the-lab-server).

### Workshop morning

```bash
cd drone-life
set -a && . /etc/drone-life.env && set +a     # once per terminal
make preflight                                # 0 FAILED, or the doors stay shut
systemctl status drone-life || curl -s localhost:8000/healthz   # B: unit green?  A: your `make run` answering?
make bots N=3                                 # three drones move on the projector?
make reset                                    # clean slate: kills the bots, zeroes the score
```

Projector on `/` with the room code typed in; `/admin` open on the instructor
laptop. Minute-by-minute from here:
[SESSION_PLAN.md](docs/SESSION_PLAN.md#3-before-doors-open-t20).

### What to give students

The URL, the room code, and a printed [docs/CHEATSHEET.md](docs/CHEATSHEET.md).
They need only a browser — no installs. The longer handout is
[docs/STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md).

### Limits & requirements

- `MAX_STUDENTS` is **20** by default (roster = drone slots = MAVLink ports
  5760–5779); raise it in the env file for a bigger room.
- One projector view is the design point; the wifi must carry ~20 student
  pages plus the viewer, each holding a WebSocket.
- Every running script is one container at **0.5 CPU + 256 MB**: 20 pilots
  running at once want ~10 cores of headroom and ~6 GB RAM. `make load
  LOAD_BOTS=20` tells you whether your box copes.

### Switching missions

`MISSION` is read at boot: edit it in `/etc/drone-life.env`
(`sudo sed -i 's/^MISSION=.*/MISSION=siege/' /etc/drone-life.env` — `sudo`
even on deploy A: `/etc` is root's, so a plain `sed -i` cannot write there),
restart the server (`sudo systemctl restart drone-life`, or Ctrl-C and
`make run` again), then `make reset` for a fresh score. The two rehearsed procedures (with and
without carrying the score over) are
[SESSION_PLAN.md → Transition procedures](docs/SESSION_PLAN.md#5-transition-procedures).

### When something breaks

The symptom → check → fix table is [DEPLOY.md → When things break](docs/DEPLOY.md#when-things-break).
The three you will actually need:

- Is the sim alive? `curl -s localhost:8000/healthz` (`"ok": true`).
- Every submit says "runner image … is not built": `make image` as the user
  the server runs as, no restart needed — under systemd, also check the unit's
  `XDG_RUNTIME_DIR` uid (the runbook explains).
- A script won't die: **kill** in `/admin`, or `podman ps --filter label=drone-life=1`
  then `podman rm -f -t 0 <id>`. Port 8000 busy after a crash: `make kill-prod`.

## Missions

Select with `MISSION=<name>` (env file for deploys, `MISSION=siege make dev-server` for dev).

| mission | one line |
|---|---|
| `freefly` | no objectives, no score — the shared sky; warm-up |
| `delivery` | hover low over a crate, carry it to the pad at (0,0), team score |
| `canyon` | two pre-placed steel walls — terrain in the sky; drones crash into and land on them |
| `rampart` | guided building: ferry steel from the quarry, stack it along the ghost wall |
| `forge` | free building in clay: close a ring of 6 tiles and a furnace lights |
| `siege` | tower defense: grunts, runners, brutes, sappers and a champion every 5th wave march on the Keep through up to three gates — zap them, squish them under tiles, stack 3 steel into auto-firing watchtowers; the wall shows wave, countdown and Keep hp, and a reset reads out the round |

Demo bots (`make bots N=3 SCRIPT=<bot>`) are mission-specific; a bot on the
wrong mission just idles. `MODE=container` runs them through the real sandbox.

| bot | mission |
|---|---|
| `bot_patrol` | any |
| `bot_courier` | `delivery` |
| `bot_builder` | `rampart` |
| `bot_siege` | `siege` (zapper) |
| `bot_tower` | `siege` (ferries steel to the announced site, raises watchtowers) |

Missions are plugins (`server/app/game/missions/`): implement the small
`Mission` interface, register it, done — [docs/MISSIONS.md](docs/MISSIONS.md).

## Documentation map

- [docs/SESSION_PLAN.md](docs/SESSION_PLAN.md) — the instructor's day, minute by minute: arc, transitions, bots, balance knobs
- [docs/DEPLOY.md](docs/DEPLOY.md) — proxied lab-server deploy, config reference, runbook, troubleshooting, threat model
- [docs/deploy/gateway-tunnel/README.md](docs/deploy/gateway-tunnel/README.md) — optional SSH reverse tunnel from a NAT'd lab server to the gateway VM
- [docs/STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md) — the pilot's guide: helper API, GAME messages, what the pymavlink underneath does
- [docs/CHEATSHEET.md](docs/CHEATSHEET.md) — the printable one-pager for every seat
- [docs/MISSIONS.md](docs/MISSIONS.md) — the mission contract for authors (enforced by tests)
- [CONTRIBUTING.md](CONTRIBUTING.md) — architecture seams, bring-up order, where code goes

## Development

```bash
make test        # server (pytest, incl. real-mavutil flights) + web (vitest)
make lint        # ruff (server) + eslint (web); make lint-fix autofixes ruff only
make typecheck   # tsc --noEmit (web) + mypy (server)
make build       # tsc + vite build → web/dist
make dev-web     # hot-reload frontend on :5173, proxying /api and /ws to :8000 (DL_SERVER=http://host:8000 to point elsewhere)
make e2e         # a real podman container delivers a crate — needs `make image`, else it silently SKIPS
make load        # 10 bots, 60 s: tick overruns <1%, world feed ≥9 Hz (LOAD_BOTS=20 for class size)
make kill-dev    # stop stray uvicorn --reload / vite instances; kill-prod: `make run` instances + leftover containers
make clean       # rm -rf server/state web/dist — deletes every student token; never mid-class
```

CI (`.github/workflows/ci.yml`) runs lint + typecheck + tests + build on every
PR with Node 22; the podman e2e runs weekly (`e2e.yml`).

## Layout

| path | what |
|---|---|
| `server/app/sim/` | kinematic drone sim (NED, mode machine) + `DroneBackend` seam |
| `server/app/mav/` | MAVLink gateway: TCP per drone, dispatch, telemetry |
| `server/app/game/` | engine (score/feed services) + mission plugins |
| `server/app/runner/` | podman-per-student script sandbox + live logs |
| `server/app/api/` | REST + WebSocket (viewer/student feeds) |
| `server/app/preflight.py` | `make preflight` — the workshop-morning box check |
| `web/src/viewer/` | PixiJS isometric sky view |
| `web/src/submit/` | CodeMirror editor, run controls, live logs |
| `web/src/admin/` | instructor console: roster, kill/kick, reset, bots |
| `examples/` | `dronelife.py` helper, student templates, demo bots |
| `runner/` | Containerfile for the student-script sandbox image |
| `docs/` | the documentation map above; `docs/deploy/` holds the systemd unit and tunnel units |

## Gotchas we already hit for you

- mavutil is blocking: server-side only the generated dialect parser is used.
- The wire is MAVLink 2 everywhere (`MAVLINK20=1` baked into every exec path).
- `recv_match(blocking=True)` without `timeout` hangs forever — templates
  always pass timeouts.
- Script liveness = TCP close (mavutil clients don't send heartbeats).
- Rootless podman: script files must be 0644 through the uid mapping;
  `--rm` leaks on SIGKILL → the server sweeps by label at startup.
- STATUSTEXT caps at 50 chars — game messages are designed terse.
- systemd's `%U` in a system unit is root's uid, not `User=`'s — the shipped
  unit hardcodes `XDG_RUNTIME_DIR` for that reason, and preflight checks it.
