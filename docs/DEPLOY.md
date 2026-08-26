# Deploying drone-life on the lab server (behind the OCI VM proxy)

One machine runs everything. One HTTP port (8000) is the only thing the proxy
needs to reach. MAVLink stays on 127.0.0.1 — unreachable from outside by
construction; student containers reach it through slirp4netns host-loopback
(10.0.2.2).

## One-time setup

```bash
# 1. a dedicated non-root user
sudo useradd -m dronelife
sudo loginctl enable-linger dronelife     # rootless podman under systemd needs this

# 2. verify rootless podman prerequisites (as dronelife)
grep dronelife /etc/subuid /etc/subgid    # must have ranges; add with usermod --add-subuids
podman system migrate                      # once, after any subuid change
command -v slirp4netns                     # required for the container network mode

# 3. code + toolchain
sudo -iu dronelife
git clone <repo> /opt/drone-life && cd /opt/drone-life
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
cd server && uv sync && cd ..
# node only needed to build the frontend (or build web/dist elsewhere and copy)
cd web && npm ci && npm run build && cd ..

# 4. the sandbox image
make image

# 5. config — the server refuses to start on the placeholder values, so fill
#    these in for real (ADMIN_TOKEN: `openssl rand -base64 24`)
sudo tee /etc/drone-life.env <<'EOF'
ROOM_CODE=pick-something-short
ADMIN_TOKEN=long-random-string
MISSION=delivery
# the OCI VM's address as the lab server sees it — without this every student
# shares one rate-limit bucket; see "OCI VM reverse proxy" below
FORWARDED_ALLOW_IPS=10.0.0.5
EOF
sudo chmod 600 /etc/drone-life.env
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
systemctl status drone-life           # green?
make bots N=3 HOST=localhost:8000 ADMIN_TOKEN=...   # smoke: three drones on the projector
make reset HOST=localhost:8000 ADMIN_TOKEN=...      # clean slate between sessions
```

- Projector: open `https://drones.example.org/`, enter the room code once.
- Students: `https://drones.example.org/submit` + the room code.
- Instructor console: `https://drones.example.org/admin` + the admin token —
  live roster, kill a stuck script, kick a student, reset the world, spawn bots.
- A student stuck? Their **reset drone** button, the console's **kill script**, or:
  `curl -X POST .../api/v1/admin/kill -H "X-Admin-Token: ..." -d '{"student_id":"s3"}'`
- Between class sessions: `make reset` (kills all scripts, respawns drones,
  fresh crates + score). `server/state/` keeps the roster across restarts —
  delete it for a completely fresh class.

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
oracle. This depends on `FORWARDED_ALLOW_IPS` being set (see the proxy section)
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
