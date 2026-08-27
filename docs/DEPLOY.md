# Deploying drone-life on the lab server (behind the OCI VM proxy)

One machine runs everything. One HTTP port (8000) is the only thing the proxy
needs to reach. MAVLink stays on 127.0.0.1 — unreachable from outside by
construction; student containers reach it through slirp4netns host-loopback
(10.0.2.2).

## One-time setup

Steps 1–2 run as your admin account, steps 3–4 as `dronelife`, step 5 back as
admin — the prompts below mark the switches.

```bash
# 1. a dedicated non-root user (admin account)
sudo useradd -m dronelife
sudo loginctl enable-linger dronelife     # rootless podman under systemd needs this
sudo install -d -o dronelife -g dronelife /opt/drone-life   # dronelife can't mkdir in /opt
# (already cloned /opt/drone-life as another user in an earlier attempt?
#  sudo chown -R dronelife:dronelife /opt/drone-life — or uv/npm hit EACCES)

# 2. rootless podman prerequisites (still admin — usermod needs root)
grep dronelife /etc/subuid /etc/subgid    # must show a range in BOTH files; if not:
#   sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 dronelife
command -v slirp4netns                    # required for the container network mode

# 3. code + toolchain (as dronelife)
sudo -iu dronelife
podman system migrate                     # once, after any subuid/subgid change
git clone <repo> /opt/drone-life && cd /opt/drone-life
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv → ~/.local/bin
. ~/.local/bin/env                        # put uv on PATH in this shell
# (`.`, not `source`: useradd gave dronelife plain /bin/sh, where source doesn't exist)
cd server && uv sync && cd ..
# node ≥ 20, only needed to build the frontend (or build web/dist elsewhere and copy)
cd web && npm ci && npm run build && cd ..

# 4. the sandbox image (still dronelife — the rootless image store is per-user)
make image
exit                                      # back to the admin account

# 5. config. The generated ADMIN_TOKEN is real — keep it. Swap ROOM_CODE for
#    something students can type from the projector. Don't hand-type either:
#    the startup guard only rejects the literal defaults (`classroom` /
#    `change-me`) and empty — any other weak value boots without complaint.
sudo tee /etc/drone-life.env <<EOF
ROOM_CODE=$(openssl rand -hex 4)
ADMIN_TOKEN=$(openssl rand -base64 24)
MISSION=delivery
# the OCI VM's address as the lab server sees it — without this every student
# shares one rate-limit bucket; see "OCI VM reverse proxy" below
FORWARDED_ALLOW_IPS=10.0.0.5
EOF
sudo chown root:dronelife /etc/drone-life.env
sudo chmod 640 /etc/drone-life.env   # dronelife must read it: preflight sources it
```

## Configuration reference

Every knob is an env var read by `server/app/config.py` (pydantic-settings;
a `.env` file in `server/` also works for dev). The HTTP bind address and port
are **not** settings — they are uvicorn CLI flags (see the Makefile `run`
target and the systemd unit).

| variable | default | meaning |
|---|---|---|
| `ROOM_CODE` | `classroom` | what students type to join — override for any reachable deploy |
| `ADMIN_TOKEN` | `change-me` | instructor console + admin API token — override likewise |
| `MISSION` | `delivery` | which mission plugin runs (`canyon`, `delivery`, `forge`, `freefly`, `rampart`, `siege`) |
| `MAX_STUDENTS` | `20` | roster cap = drone slots = MAVLink ports |
| `SIM_SEED` | `42` | mission RNG seed (crate spawns, wave gates) |
| `SIM_UNTHROTTLED` | `false` | tests only: run the driver without sleeping |
| `MAVLINK_HOST` | `127.0.0.1` | MAVLink listeners bind here — keep on loopback |
| `MAVLINK_BASE_PORT` | `5760` | slot N's drone listens on base+N |
| `RUNNER_IMAGE` | `drone-life-runner:latest` | sandbox image for student scripts |
| `RUNNER_NETWORK` | `slirp4netns:allow_host_loopback=true` | podman network for sandboxes |
| `DRONE_HOST` | `10.0.2.2` | host loopback as seen from inside a container |
| `RUN_MAX_SECONDS` | `900` | wall-clock cap per script run |
| `STATE_DIR` | `state` | roster/score snapshot dir (relative to `server/`) |
| `STATIC_DIR` | `../web/dist` | built frontend served at `/` |
| `JOIN_RATE_LIMIT_PER_MINUTE` | `30` | per-IP join attempts; wrong codes on `/world` and `/ws/viewer` spend it too |
| `SUBMIT_RATE_LIMIT_PER_MINUTE` | `10` | per-student script submissions, guards container churn |
| `ALLOW_DEFAULT_SECRETS` | `false` | dev only: boot on the placeholder `ROOM_CODE`/`ADMIN_TOKEN` |

One variable in `/etc/drone-life.env` is **not** a `config.py` setting:
`FORWARDED_ALLOW_IPS` is read by uvicorn itself (it is the default for
`--forwarded-allow-ips`; pydantic ignores it). It is the comma-separated list
of peers whose `X-Forwarded-For` header is believed — IPs or CIDRs, defaulting
to `127.0.0.1`. Set it to the proxy's address, never to `*`.

The server **refuses to start** when `ROOM_CODE` or `ADMIN_TOKEN` is still the
placeholder (`classroom` / `change-me`) or is empty — uvicorn aborts with the
reason on stderr and exits non-zero, so a misconfigured unit fails loudly at
`systemctl start` instead of quietly serving an open room. `make dev-server`
sets `ALLOW_DEFAULT_SECRETS=1`; `make run` deliberately does not.

## systemd

```bash
sudo cp docs/deploy/drone-life.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now drone-life
curl -s localhost:8000/healthz
```

Note: the unit runs as user `dronelife` via `User=`; because rootless podman
needs a session, `enable-linger` (step 1) is what makes containers work when
nobody is logged in. The unit assumes the clone lives at `/opt/drone-life`
and uv at `/home/dronelife/.local/bin/uv` — edit both paths if yours differ,
and put `MISSION=` in `/etc/drone-life.env` or the deploy runs `delivery`.

## OCI VM reverse proxy

nginx on the OCI VM, forwarding to the lab server (here via a wireguard/SSH
tunnel address `LAB`):

```nginx
server {
    listen 443 ssl;
    server_name drones.example.org;
    # ... ssl_certificate ...

    location / {
        proxy_pass http://LAB:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # WebSockets: /ws/viewer and /ws/student
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1h;      # projector viewer sits idle-but-connected
        proxy_buffering off;        # live frames go straight out, never queued
    }
}
```

Lab-server firewall: allow 8000 **only** from the OCI VM's address.

**Pair that firewall rule with `FORWARDED_ALLOW_IPS`** (`/etc/drone-life.env`,
same address). `--proxy-headers` is already on in the systemd unit, but uvicorn
only believes `X-Forwarded-For` from peers in that list — default `127.0.0.1`,
which the proxy is not. Until it is set, every request looks like it came from
the proxy, so the per-IP join limit becomes one *class-wide* bucket and a single
prankster hitting the join endpoint locks the whole room out. The firewall rule
is what makes trusting the header safe: nobody else can reach port 8000 to
forge one.

Residual risk worth knowing: if the whole class sits behind one school NAT,
even a correct `X-Forwarded-For` shows one address for everyone. Raise the
ceiling for the day (`JOIN_RATE_LIMIT_PER_MINUTE=120` in the env file) rather
than keying the limiter on anything else a client can set.

## Workshop-day runbook

```bash
# 0. before anything else: does this box have what a submit needs?
sudo -iu dronelife
cd /opt/drone-life && set -a && . /etc/drone-life.env && set +a && make preflight

systemctl status drone-life           # green?
make bots N=3 HOST=localhost:8000 ADMIN_TOKEN=...   # smoke: three drones on the projector
make reset HOST=localhost:8000 ADMIN_TOKEN=...      # clean slate between sessions
```

`make preflight` checks podman, the runner image, subuid/subgid, slirp4netns,
the MAVLink port range, `web/dist`, the state dir and disk, then runs one real
container. Exit 1 means don't start class — every failure line names its fix.
It sources the env file so it checks the deploy you are about to run; without
that it checks the defaults instead. `make preflight PREFLIGHT_ARGS=--no-smoke`
skips the container run when you only want the fast checks.

- Projector: open `https://drones.example.org/`, enter the room code once.
- Students: `https://drones.example.org/submit` + the room code.
- Instructor console: `https://drones.example.org/admin` + the admin token —
  live roster, kill a stuck script, kick a student, reset the world, spawn bots.
- A student stuck? Their **reset drone** button, the console's **kill script**, or:
  `curl -X POST .../api/v1/admin/kill -H "X-Admin-Token: ..." -d '{"student_id":"s3"}'`
- Between class sessions: `make reset` (kills all scripts, respawns drones,
  fresh crates + score). `server/state/` keeps the roster across restarts —
  delete it for a completely fresh class.
- Minute-by-minute session plan (mission order, transitions, bots, balance
  knobs): `docs/SESSION_PLAN.md`.

## When things break

Server logs are `journalctl -u drone-life -f`. The instructor console's health
line is the fastest read on whether the sim itself is alive.

| symptom | check | fix |
|---|---|---|
| every submit says "runner image … is not built" | `podman image exists drone-life-runner:latest` | `make image` — no restart needed, the next submit picks it up |
| a student's log ends "the sandbox failed to start (podman exit 125)" | `journalctl -u drone-life \| grep podman` | usually the image or subuid ranges: `make preflight` names which |
| projector frozen, console says **SIM STALLED** | `curl -s localhost:8000/healthz` | `journalctl -u drone-life -n 100` for the traceback, then `systemctl restart drone-life` |
| console health line shows climbing "sim errors" | server log has `driver tick failed` | a mission or sim bug — restart clears it, the traceback names the file |
| server won't start, port 8000 busy | `ss -ltnp 'sport = :8000'` | `make kill-prod` (uvicorn + leftover containers), then start again |
| joins return 500 | `ss -ltnp` over 5760–5779 | something squats a MAVLink port — kill it, restart |
| students can reach the page but not join | the room code they were given vs `ROOM_CODE` in `/etc/drone-life.env` | tell them the right one — a wrong code is a clear message on their page, not a hang |
| a script won't die | console **kill script** | `podman ps --filter label=drone-life=1` then `podman rm -f -t 0 <id>` |
| server boots but serves no page | `ls /opt/drone-life/web/dist` | `make build` — the server starts fine without it and silently serves nothing |
| boot fails on a corrupt snapshot | `journalctl -u drone-life -n 50` | `rm server/state/snapshot.json` and restart — roster, tokens and score are lost, students re-join and same names take the same slots |
| proxy or OCI VM dead | can you reach the lab server directly? | hotspot fallback: `make run` on the lab server binds `0.0.0.0:8000`, students use `http://<lab-ip>:8000/submit`. Open the room's firewall to that port only, and put the URL on the projector |

"Flaky" is not a diagnosis. A student whose drone flew home on its own didn't
hit a bug: a script that disconnects gets 10 s of grace, then auto-RTL with
`script gone: returning home`.

## Reading /healthz

`curl -s localhost:8000/healthz` — no token needed.

| field | healthy | meaning |
|---|---|---|
| `ok` | `true` | the driver is alive and ticked in the last 5 s |
| `driver_alive` | `true` | the 20 Hz task exists and hasn't finished |
| `last_tick_age_s` | < 0.2 | seconds since the last *successful* tick |
| `ticks` / `overruns` | overruns/ticks < 1% | counters since boot, not rates — take a delta |
| `driver_errors` | `0` | ticks that raised; anything above 0 is in the server log |
| `drones` / `students` / `score` / `mission` / `uptime_s` | — | what's flying, who's in, where the game is |

`ok` says nothing about podman or the image — those cost a subprocess and
belong to `make preflight`, not to a poll that runs every few seconds.

## Restarts and mission switches

A restart keeps the **roster, student tokens and the team score** (from
`server/state/snapshot.json`, written every 30 s and on exit). It does **not**
keep drone positions, mission entities (crates, tiles, waves) or running
scripts: the mission runs `setup()` again and every container is swept. Students
do not need to re-join — their page reconnects with the token it already has.

Switching missions is a restart, since `MISSION` is read at boot:

```bash
sudoedit /etc/drone-life.env        # MISSION=siege
systemctl restart drone-life        # ~5 s
make reset HOST=localhost:8000 ADMIN_TOKEN=...   # fresh score for the new mission
```

Footguns:

- `make clean` deletes `server/state/` — every token with it. Students would
  have to re-join. It is not part of any deploy step.
- The systemd unit never reads the Makefile. `MISSION=` on a `make` command
  line only affects a server you start with `make dev-server` / `make run`;
  under systemd only `/etc/drone-life.env` counts.
- Rehearse the real class size on the real hardware before the day:
  `make load LOAD_BOTS=20`, and watch the console's overrun percentage.

## Threat model notes

The setting is a supervised classroom on a lab server, reachable from the
internet through the OCI VM. The adversary we design for is a bored student
with a Python prompt, not a targeted attacker — but the box is internet-facing,
so the boundaries below are the ones that must actually hold.

**The sandbox.** Student code runs in rootless podman: all capabilities
dropped, `no-new-privileges`, read-only rootfs with only a 16 MB `/tmp`,
256 MB / 0.5 CPU / 64 pids, a 15 min wall cap, non-root uid, and the only
mount is their own script (read-only, 0644). `container_argv` holds that
policy in one function; `tests/test_podman_argv.py` pins every flag and
`tests/test_e2e_sandbox.py` verifies from inside a real container that the
flags actually take effect.

**Containers reach host loopback — accepted.** `allow_host_loopback` is how a
script reaches its drone's MAVLink port, but it exposes *every* loopback port
on the lab box, including other students' drones and the API. Accepted for a
supervised classroom: the API needs tokens, the room code gates joining, and
flying someone else's drone is instantly visible on the projector. Do not run
unrelated loopback-only services on this host during the workshop.

**Containers reach the internet — accepted.** slirp4netns NATs the sandbox to
the whole internet; loopback access is the *addition*, not the limit. A student
can `pip install --target /tmp`, phone home, or post data outward. Restricting
it was considered and rejected: `--network=none` breaks the MAVLink connection
students' scripts are built around, an internal netavark network loses host
loopback with it, and a host firewall rule keyed on the service uid also cuts
the server's own egress. What bounds the risk instead: the room is supervised,
runs are capped at 15 minutes and 0.5 CPU, submissions are rate-limited, and
each student's latest script sits server-side at
`state/scripts/<student-id>/current.py` (each submit overwrites it, so it is a
snapshot of what is running, not an audit trail). If a future deployment needs
egress blocked, do it in
the host firewall against the container network, and expect to test it: an
over-broad rule silently breaks every student's drone connection.

**Secrets.** The server refuses to start on the placeholder or empty
`ROOM_CODE` / `ADMIN_TOKEN` (`ALLOW_DEFAULT_SECRETS=1` overrides, dev only).
All secret compares — admin token, room code on join/`/world`/`/ws/viewer`,
and the student bearer token — are constant-time.

**Rate limits.** Joins are limited per IP, and wrong room codes on `/world` and
`/ws/viewer` spend the same budget, so none of the three is a free guessing
oracle. Once an address hits the ceiling those two endpoints refuse *every*
request from it, including one carrying the right code: answering correct
codes while declining to charge for wrong ones would leave the guessing
unbounded, only with a 429 in place of a 403. A correct code costs nothing
while the address is under its ceiling, so the projector is unaffected.
This depends on `FORWARDED_ALLOW_IPS` being set (see the proxy section)
— without it the whole class shares one bucket. Submissions are capped per
student, and each run's log output is capped at ~50 lines/s to keep a runaway
`print` loop from drowning the hub. Admin auth is deliberately *not* limited:
the token is long and random and compared in constant time, and a limiter there
would mostly hand a prankster behind the shared NAT a way to lock the
instructor out mid-class.

**WebSocket credentials travel in the URL.** `/ws/viewer?code=` and
`/ws/student?token=` put the room code and student tokens in query strings,
where the OCI VM's nginx access log records them. Accepted for a workshop;
keep those logs private and rotate the room code between classes.

**`/healthz` is unauthenticated** on purpose, so the runbook and any monitor
can check it. It returns counters only — drones, ticks, overruns, score — no
names and no tokens.
