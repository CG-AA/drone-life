# Deploying drone-life on the lab server (behind the OCI VM proxy)

One machine runs everything. One HTTP port (8000) is the only thing the proxy
needs to reach. MAVLink stays on 127.0.0.1 — unreachable from outside by
construction; student containers reach it through slirp4netns host-loopback
(10.0.2.2).

This is the proxied deploy. The simpler one — one box on the classroom wifi,
no proxy, `make run` — is in the [README](../README.md#run-a-workshop); the
runbook and troubleshooting sections below apply to both.

## One-time setup

Three blocks, two user contexts. Do not paste the whole section at once:
`sudo -iu dronelife` opens a new interactive shell, so the blocks after it
run *inside* that shell. Prerequisites (git, make, curl, uv, Node 22, podman,
uidmap, slirp4netns) are in the [README](../README.md#what-you-need) —
install the apt packages and Node as admin first; uv is per-user and is
installed in step 3.

### Steps 1–2 — as your admin account

```bash
# 1. a dedicated non-root user. -s /bin/bash: useradd's default is /bin/sh
#    (dash), where `source` and other bashisms fail later.
sudo useradd -m -s /bin/bash dronelife
sudo loginctl enable-linger dronelife     # rootless podman under systemd needs this
sudo install -d -o dronelife -g dronelife /opt/drone-life   # dronelife can't mkdir in /opt
# (already cloned /opt/drone-life as another user in an earlier attempt?
#  sudo chown -R dronelife:dronelife /opt/drone-life — or uv/npm hit EACCES)

# 2. rootless podman prerequisites (still admin — usermod needs root)
grep dronelife /etc/subuid /etc/subgid    # must show a range in BOTH files; if not:
#   sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 dronelife
command -v slirp4netns                    # required for the container network mode
```

### Steps 3–4 — as `dronelife`

```bash
sudo -iu dronelife                        # opens a new shell; the rest of this block runs in it
```

```bash
# 3. code + toolchain
podman system migrate                     # once, after any subuid/subgid change
git clone https://github.com/CG-AA/drone-life.git /opt/drone-life && cd /opt/drone-life
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv → ~/.local/bin
. ~/.local/bin/env                        # put uv on PATH in this shell (works in sh and bash)
cd server && uv sync && cd ..
# Node ≥ 20 is only needed to build the frontend (or build web/dist elsewhere and copy it in)
cd web && npm ci && npm run build && cd ..

# 4. the sandbox image (still dronelife — the rootless image store is per-user)
make image
exit                                      # back to the admin account
```

### Step 5 — as your admin account again

```bash
# 5. config. The generated ADMIN_TOKEN is real — keep it. Swap ROOM_CODE for
#    something students can type from the projector. Don't hand-type either:
#    the startup guard only rejects the literal defaults (`classroom` /
#    `change-me`) and empty — any other weak value boots without complaint.
sudo tee /etc/drone-life.env <<EOF
ROOM_CODE=$(openssl rand -hex 4)
ADMIN_TOKEN=$(openssl rand -base64 24)
# the day starts on freefly (SESSION_PLAN.md §3); switch missions later by
# editing this line and restarting — see "Restarts and mission switches"
MISSION=freefly
# what the projector's "join the sky at" card shows. The projector page is
# usually opened on localhost or the LAN, and its own address would send
# students to the wrong place — give them the one they can reach.
PUBLIC_URL=http://203.0.113.5:8000
# the OCI VM's address as the lab server sees it — without this every student
# shares one rate-limit bucket; see "OCI VM reverse proxy" below. Through the
# SSH tunnel in docs/deploy/gateway-tunnel/ it is 127.0.0.1.
# REPLACE 10.0.0.5 with the proxy's address as the lab server sees it — a wrong
# value fails silently and puts the whole class in one rate-limit bucket, where
# 30 wrong codes lock everyone out (the projector too); `make preflight` warns
# when it is unset. Through the ssh reverse tunnel the proxy arrives from
# 127.0.0.1 (uvicorn's default) — see docs/deploy/gateway-tunnel/README.md.
FORWARDED_ALLOW_IPS=10.0.0.5
EOF
# This file is what every room shares. The one-room deploy also needs the
# room's own file — sh docs/deploy/rooms/mkrooms.sh 0 | sudo sh writes
# /etc/drone-life.d/main.env (PORT, MAVLink range, seats). Several rooms of
# ~20 for the small missions: docs/ROOMS.md.
sudo chown root:dronelife /etc/drone-life.env
sudo chmod 640 /etc/drone-life.env   # dronelife must read it: the unit's EnvironmentFile= does, and so does the runbook's `. /etc/drone-life.env`
```

## Configuration reference

Every knob is an env var read by `server/app/config.py` (pydantic-settings;
a `.env` file in `server/` also works for dev). The HTTP bind address and port
are **not** settings — they are uvicorn CLI flags (see the Makefile `run`
target); the systemd unit passes `PORT` from the room's env file
(`/etc/drone-life.d/<id>.env`, [ROOMS.md](ROOMS.md)).

| variable | default | meaning |
|---|---|---|
| `ROOM_CODE` | `classroom` | what students type to join — override for any reachable deploy |
| `ADMIN_TOKEN` | `change-me` | instructor console + admin API token — override likewise |
| `MISSION` | `delivery` | which mission plugin runs (`canyon`, `delivery`, `forge`, `freefly`, `rampart`, `siege`) |
| `MAX_STUDENTS` | `20` | roster cap = drone slots = MAVLink ports (64 for the siege room) |
| `ROOM_ID` | `main` | this process's name: the systemd instance, its podman label, its state dir. Lowercase letters, digits, `-`, `_` |
| `ROOM_LABEL` | *(empty)* | what the student page's room list calls this room; empty = "Room N" from the id |
| `ROOMS` | *(empty)* | `r1,r2,…` — the small rooms behind the proxy that the student page lists with live counts; empty = no list ([ROOMS.md](ROOMS.md)) |
| `PUBLIC_URL` | *(empty)* | what the projector's "join the sky at" card shows, e.g. `http://203.0.113.5:8000` — the address **students** can reach, which is rarely where the projector page itself was opened (localhost, the LAN). Empty = the page's own origin |
| `SIM_SEED` | `42` | mission RNG seed (crate spawns, wave gates) |
| `SIM_UNTHROTTLED` | `false` | tests only: run the driver without sleeping |
| `MAVLINK_HOST` | `127.0.0.1` | MAVLink listeners bind here — keep on loopback |
| `MAVLINK_BASE_PORT` | `5760` | slot N's drone listens on base+N |
| `RUNNER_IMAGE` | `drone-life-runner:latest` | sandbox image for student scripts |
| `RUNNER_NETWORK` | `slirp4netns:allow_host_loopback=true` | podman network for sandboxes |
| `DRONE_HOST` | `10.0.2.2` | host loopback as seen from inside a container |
| `RUN_MAX_SECONDS` | `900` | wall-clock cap per script run |
| `STATE_DIR` | `state` | roster/score snapshot dir (relative to `server/`); the unit sets `state/<ROOM_ID>`; also `rounds.jsonl` there — one line per played siege round, appended at reset, survives resets and restarts, deleted by `make clean` |
| `EXTRA_BOT_SCRIPTS` | (empty) | dev only: more scripts `/admin` may spawn as bots, by path under `examples/` without `.py`, comma-separated (`answers/quest_route,…`) — the worked answers stay out of the default allowlist so a class never meets them before the wrap |
| `STATIC_DIR` | `../web/dist` | built frontend served at `/` |
| `JOIN_RATE_LIMIT_PER_MINUTE` | `30` | per-IP join attempts; wrong codes on `/world` and `/ws/viewer` spend it too |
| `JOIN_STRIKES` | `3` | wrong room codes from one IP before it is locked out of `/join`, `/world` and the viewer (right code or not); `0` disables |
| `JOIN_LOCKOUT_S` | `900` | how long that lockout lasts; `0` = until restart. `POST /api/v1/admin/unlock` (admin token) lifts all lockouts and bans now |
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

One template unit, one instance per room ([ROOMS.md](ROOMS.md)); the
one-room deploy is the instance called `main`:

```bash
cd /opt/drone-life
sudo cp docs/deploy/drone-life@.service /etc/systemd/system/
# the unit hardcodes XDG_RUNTIME_DIR=/run/user/1001 — make it *your* dronelife uid
sudo sed -i "s#/run/user/[0-9]*#/run/user/$(id -u dronelife)#" /etc/systemd/system/drone-life@.service
grep XDG_RUNTIME_DIR /etc/systemd/system/drone-life@.service   # /run/user/<uid of dronelife>
sh docs/deploy/rooms/mkrooms.sh 0 | sudo sh     # /etc/drone-life.d/main.env: PORT=8000, 64 seats
sudo systemctl daemon-reload
sudo systemctl enable --now drone-life@main
curl -s localhost:8000/healthz
```

Notes on the unit ([docs/deploy/drone-life@.service](deploy/drone-life@.service)):

- `%i` is the room: `ROOM_ID=%i`, `STATE_DIR=state/%i`, and
  `EnvironmentFile=/etc/drone-life.d/%i.env` on top of the shared
  `/etc/drone-life.env`. The room file is required and there is no `PORT`
  default, on purpose — an instance nobody wrote down fails at start
  instead of silently binding a neighbour's port.
- It runs as user `dronelife` via `User=`; because rootless podman needs a
  session, `enable-linger` (step 1) is what makes containers work when nobody
  is logged in. It assumes the clone lives at `/opt/drone-life` and uv at
  `/home/dronelife/.local/bin/uv` — edit both paths if yours differ.
- **`XDG_RUNTIME_DIR` is a literal uid, on purpose.** `%U` in a *system* unit
  expands to the service manager's uid (0), not `User=`'s, so podman inside
  the service looks in `/run/user/0`, sees no image, and every submit fails
  with "runner image … is not built" — while `make preflight` in a
  `sudo -iu dronelife` shell passes. The `sed` above sets the right uid; the
  file's comment says the same.
- **`StartLimitBurst=5` / `StartLimitIntervalSec=60`**: a bad env file
  (placeholder secrets, unknown `MISSION`) makes the server exit non-zero
  deliberately. The limit stops systemd from restarting it every 3 s forever
  behind a green-looking status: after 5 failures in a minute the unit stays
  *failed* — read `journalctl -u drone-life@main -n 50`, fix the file, then
  `sudo systemctl reset-failed drone-life@main && sudo systemctl start drone-life@main`.
- `MISSION` is read from `/etc/drone-life.env` (or a room's own file) only;
  without it the deploy runs `delivery`.

## OCI VM reverse proxy

nginx on the OCI VM, forwarding to the lab server (here via a wireguard/SSH
tunnel address `LAB`). If the lab server sits behind NAT, the autossh units in
[docs/deploy/gateway-tunnel/](deploy/gateway-tunnel/README.md) put it on the
VM's loopback: `LAB` becomes `127.0.0.1`, no lab-side firewall opening is
needed, and `FORWARDED_ALLOW_IPS` is `127.0.0.1` (that README explains why).

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

Several rooms behind the same proxy — `location /r1/ { proxy_pass http://LAB:8001/; }`
and so on, plus one tunnel forward per room — are laid out in [ROOMS.md](ROOMS.md).

Lab-server firewall: allow 8000 (and 8001–8005 with rooms) **only** from the
OCI VM's address.

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

systemctl status drone-life@main           # green? (`failed` + "start-limit-hit": see the systemd section)
make bots N=3                         # smoke: three drones on the projector (ADMIN_TOKEN comes from the sourced env file)
make reset                            # clean slate between sessions
```

`make preflight` checks podman, the runner image, subuid/subgid, slirp4netns,
the MAVLink port range, `web/dist`, the state dir and disk, the access-control
secrets (the same call the server refuses to boot on), that `MISSION` names a
real mission, that the unit's `XDG_RUNTIME_DIR` matches the service user's uid,
that `FORWARDED_ALLOW_IPS` is set, and that the room files in
`/etc/drone-life.d/` can run side by side (distinct ports and state dirs,
no MAVLink overlap, one shared code) — then runs one real container. Exit 1
means don't start class — every failure line names its fix.
`make` does **not** read `/etc/drone-life.env` by itself: the
`set -a && . /etc/drone-life.env && set +a` prefix above is what makes
preflight (and `make bots` / `make reset`, which pick up `ADMIN_TOKEN` and
`PORT` the same way) see the deploy you are about to run.
`make preflight ROOM=r2` loads `/etc/drone-life.env` and
`/etc/drone-life.d/r2.env` itself, the way that room's unit does;
`PREFLIGHT_ARGS=--all-rooms` also probes every room's MAVLink ports, and
`PREFLIGHT_ARGS=--no-smoke` skips the container run when you only want the
fast checks. Preflight checks *your shell's* environment, not the service's —
for that, compare `systemctl show drone-life@main -p Environment` with
`id -u dronelife`.

- Projector: open `https://drones.example.org/`, enter the room code once.
- Students: `https://drones.example.org/submit` + the room code.
- Instructor console: `https://drones.example.org/admin` + the admin token —
  live roster, kill a stuck script, kick a student, reset the world, spawn bots.
- A student stuck? Their **reset drone** button, the console's **kill script**, or:
  `curl -X POST .../api/v1/admin/kill -H "X-Admin-Token: ..." -d '{"student_id":"s3"}'`
- Between class sessions: `make reset` (kills all scripts, respawns drones,
  fresh crates + score). `server/state/main/` keeps the roster across restarts —
  delete it for a completely fresh class.
- Minute-by-minute session plan (mission order, transitions, bots, balance
  knobs): `docs/SESSION_PLAN.md`.

## When things break

Server logs are `journalctl -u drone-life@main -f`. The instructor console's health
line is the fastest read on whether the sim itself is alive.

| symptom | check | fix |
|---|---|---|
| every submit says "runner image … is not built" | `podman image exists drone-life-runner:latest` | `make image` — no restart needed, the next submit picks it up |
| every submit says "podman is not working here" | `make preflight`, then `journalctl -u drone-life@main \| grep podman` | podman failed for a reason that is not a missing image — usually `XDG_RUNTIME_DIR` or subuid. Probe it **as the service does**, not from your shell (a login shell gets a working runtime dir from PAM and will lie to you): `sudo -u dronelife XDG_RUNTIME_DIR=/run/user/$(id -u dronelife) podman image exists drone-life-runner:latest` |
| a student's log ends "the sandbox failed to start (podman exit 125)" | `journalctl -u drone-life@main \| grep podman` | usually the image or subuid ranges: `make preflight` names which |
| projector frozen, console says **SIM STALLED** | `curl -s localhost:8000/healthz` | `journalctl -u drone-life@main -n 100` for the traceback, then `systemctl restart drone-life@main` |
| console health line shows climbing "sim errors" | server log has `driver tick failed` | a mission or sim bug — restart clears it, the traceback names the file |
| server won't start, port 8000 busy | `ss -ltnp 'sport = :8000'` | `make kill-prod` (every uvicorn + leftover container on the box), then start again |
| a room's unit fails at once with uvicorn complaining about `--port` | `ls /etc/drone-life.d/` | that instance has no env file, or the file has no `PORT` — [ROOMS.md](ROOMS.md) |
| two rooms fight over MAVLink ports (joins 500 in one of them) | `make preflight ROOM=r1 PREFLIGHT_ARGS=--all-rooms` | the `rooms` line names the overlap; room N is `5760+100N` |
| joins return 500 | `ss -ltnp` over 5760–5779 | something squats a MAVLink port — kill it, restart |
| students can reach the page but not join | the room code they were given vs `ROOM_CODE` in `/etc/drone-life.env` | tell them the right one — a wrong code is a clear message on their page, not a hang |
| console says **server unreachable** while `curl localhost:8000/healthz` is 200 | the reason in parentheses on that line; F12 shows no `/api/v1/admin/students` request at all | the browser refused the request before sending it: `…value 9679…` / "masked dots" = the token was pasted from a masked field (`●●●`) — copy the plain text; `Failed to fetch` = an extension blocking `/admin` URLs — incognito window or whitelist |
| a script won't die | console **kill script** | `podman ps --filter label=drone-life=1` (one room: `label=drone-life-room=r2`) then `podman rm -f -t 0 <id>` |
| server boots but serves no page | `ls /opt/drone-life/web/dist` | `make build`, then `systemctl restart drone-life@main` — the static mount is decided at boot, so a server that started without `web/dist` keeps serving nothing until restarted |
| every submit 503s "runner image … is not built" under systemd, but `make preflight` passes in a `sudo -iu dronelife` shell | `systemctl show drone-life@main -p Environment` vs `id -u dronelife` | the unit's `XDG_RUNTIME_DIR` uid is wrong (the `%U` trap) — fix it in `/etc/systemd/system/drone-life@.service`, `daemon-reload`, restart |
| `systemctl status` shows `failed` with "start-limit-hit" and won't come back | `journalctl -u drone-life@main -n 50` | the env file is bad (placeholder secrets / unknown `MISSION`) — fix it, then `sudo systemctl reset-failed drone-life@main && sudo systemctl start drone-life@main` |
| boot fails on a corrupt snapshot | `journalctl -u drone-life@main -n 50` | `rm server/state/main/snapshot.json` and restart — roster, tokens and score are lost, students re-join and same names take the same slots |
| proxy or OCI VM dead | can you reach the lab server directly? | hotspot fallback: `set -a && . /etc/drone-life.env && set +a && make run` on the lab server binds `0.0.0.0:8000`, students use `http://<lab-ip>:8000/submit`. (Sourcing the env file is not optional — bare `make run` uses the Makefile's placeholder secrets and refuses to start.) Open the room's firewall to that port only, and put the URL on the projector |

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
`server/state/main/snapshot.json`, written every 30 s and on exit). It does **not**
keep drone positions, mission entities (crates, tiles, waves) or running
scripts: the mission runs `setup()` again and every container is swept. Students
do not need to re-join — their page reconnects with the token it already has.

Switching missions is a restart, since `MISSION` is read at boot:

```bash
sudo sed -i 's/^MISSION=.*/MISSION=siege/' /etc/drone-life.env
sudo systemctl restart drone-life@main   # ~5 s
set -a && . /etc/drone-life.env && set +a && make reset   # fresh score for the new mission
```

(The first two lines need your admin account; `make reset` works from any
account that can read the env file — root or `dronelife`.)

Footguns:

- `make clean` deletes `server/state/` — every room, every token with it.
  Students would have to re-join. It is not part of any deploy step.
- The systemd unit never reads the Makefile. `MISSION=` on a `make` command
  line only affects a server you start with `make dev-server` / `make run`;
  under systemd only `/etc/drone-life.env` (and the room's own file) counts.
- Moving the class from the small rooms into the big one is a merge, not a
  restart: [ROOMS.md](ROOMS.md), "The day".
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
