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

# 5. config
sudo tee /etc/drone-life.env <<'EOF'
ROOM_CODE=pick-something-short
ADMIN_TOKEN=long-random-string
EOF
sudo chmod 600 /etc/drone-life.env
```

## systemd

```bash
sudo cp docs/deploy/drone-life.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now drone-life
curl -s localhost:8000/healthz
```

Note: the unit runs as user `dronelife` via `User=`; because rootless podman
needs a session, `enable-linger` (step 1) is what makes containers work when
nobody is logged in.

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

- Student code runs in rootless podman: no caps, read-only rootfs, 256 MB /
  0.5 CPU / 64 pids, 15 min wall cap, only mount is their own script (ro).
- `allow_host_loopback` means containers can reach host loopback *ports* —
  i.e. other drones' MAVLink and the API. Accepted for a supervised classroom:
  the API requires tokens, MAVLink "hijacking" another drone is visible on the
  projector, and the room code gates joining at all.
- Join endpoint is rate-limited per IP against room-code guessing.
