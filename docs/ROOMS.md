# Rooms: several small servers for the teaching blocks, one big one for siege

At 64 pilots freefly and delivery are a firehose — pad labels pile up, the
feed is unreadable, one crate per pilot carpets the floor — while siege is
the mission that *wants* the crowd. So the day runs in two shapes:

- **warm-up and teaching blocks:** five rooms of up to 20, each its own
  server process behind the proxy on `/r1/` … `/r5/`, each with its own
  projector page, **all on the same classroom code**;
- **the main event:** one 64-seat siege at `/`, seeded with everyone's
  roster (not their score) from the small rooms.

One build, one repo checkout, one box: the rooms differ only in what their
env file says. This page is the whole story; [DEPLOY.md](DEPLOY.md) is the
single-room setup it builds on.

## The convention

| instance (`%i`) | URL      | HTTP `PORT` | `MAVLINK_BASE_PORT` | `MAX_STUDENTS` | `STATE_DIR`  |
|-----------------|----------|-------------|---------------------|----------------|--------------|
| `main`          | `/`      | 8000        | 5760 (5760–5823)    | 64             | `state/main` |
| `r1` … `r5`     | `/rN/`   | 8000+N      | 5760+100·N          | 20             | `state/rN`   |

Room *i* is HTTP `800i` and MAVLink `5760+100i` — one rule, and no two
ranges can overlap under 100 seats. `make preflight` refuses a layout that
breaks it.

Two kinds of file on the lab box, both read by the template unit
[`docs/deploy/drone-life@.service`](deploy/drone-life@.service):

- **`/etc/drone-life.env`** — what every room shares: `ROOM_CODE`,
  `ADMIN_TOKEN`, `MISSION`, `PUBLIC_URL`, the join-limiter knob for how
  students reach the box (`JOIN_RATE_LIMIT_PER_MINUTE` on a direct `:8000`
  tunnel, `FORWARDED_ALLOW_IPS` behind nginx — DEPLOY.md), and
  `ROOMS=r1,r2,r3,r4,r5` (the rooms the student page lists).
- **`/etc/drone-life.d/<id>.env`** — one per instance: `PORT`,
  `MAVLINK_BASE_PORT`, `MAX_STUDENTS`, `STATE_DIR`, and optionally
  `ROOM_LABEL` ("Room 1 — north tables"), or any shared value overridden
  for that room (`PUBLIC_URL=https://…/r1` puts the room's own address on its
  projector; `MISSION=` lets one room play something else). Values here win
  over the shared file. `sh docs/deploy/rooms/mkrooms.sh 5 | sudo sh` writes
  all six by the convention; [`deploy/rooms/`](deploy/rooms/) has examples.

The unit sets `ROOM_ID=%i` (the instance name) and `STATE_DIR=state/%i`
itself, and passes `PORT` to uvicorn — there is **no `PORT` default**, so a
room with no file fails at `systemctl start` instead of silently sharing
`:8000` with its neighbour.

## What students see

Every projector shows the same code. `https://host/submit` (the big room's
page) lists the rooms with live counts — `Room 1 · 12/20 · freefly` — and a
row is a link to that room's `/rN/submit`; a full room is not a link, a room
whose server is down says *closed*, and when every room is closed the list
steps aside and the plain join form is what's left (siege time). A page
inside a room shows "you are in Room 2 · switch room". The counts come from
each room's own `/healthz` (`students`, `max_students`, `label`), which is
unauthenticated and does not touch the join limiter.

If a room's `PUBLIC_URL` is set to its own prefix, that room's projector
sends its tables straight to `/rN/submit`; leave it out and the card shows
the shared URL, whose list does the choosing. Either works — the picker is
for whoever walks in through the front door.

Room codes, tokens and names live in `localStorage` for the origin, which
every room shares. That is what makes the merge zero-touch (below); its one
side effect is that a page that joined room 1 and then opens room 2 finds
its token refused, clears it, and shows the join form — join again, no harm.

## The proxy

nginx on the OCI VM: the `location /` block from DEPLOY.md stays for the
big room; each small room gets the same block with its prefix stripped.
Every block needs the WebSocket upgrade headers, `proxy_read_timeout 1h`
and `proxy_buffering off` from the original.

```nginx
# room N — repeat for r1 … r5, LAB:800N. The trailing slash on proxy_pass
# strips the prefix: the server never sees /rN, the page adds it back to
# every request it makes (web/src/shared/prefix.ts).
location = /r1 { return 301 /r1/; }
location ~ ^/(r[0-9]+)/(submit|admin)/$ { return 301 /$1/$2; }   # a hand-typed slash would fall off the room
location /r1/ {
    proxy_pass http://LAB:8001/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 1h;
    proxy_buffering off;
}
```

Through the autossh tunnel, `LAB` is `127.0.0.1` and each room needs its own
forward: set `TUNNEL_ROOM_FORWARDS` in `/etc/default/autossh-reverse-tunnel`
(the five-room value is in
[`deploy/gateway-tunnel/autossh-web-tunnel.env`](deploy/gateway-tunnel/autossh-web-tunnel.env))
and restart `autossh-web-tunnel`. On the lab side the firewall rule is
unchanged: only the VM reaches 8000–8005.

Hotspot fallback without the proxy: the rooms answer on `http://<lab-ip>:800N/submit`
directly — no prefix at all — and the big room on `:8000`.

## The day

```bash
# morning, as your admin account
sudo systemctl start drone-life@{main,r1,r2,r3,r4,r5}
# then as dronelife, once per room (each check names its fix; ROOM= loads that room's env files)
cd /opt/drone-life && make preflight ROOM=r1 PREFLIGHT_ARGS=--all-rooms
# projectors: https://host/r1/ … /r5/ (each asks for the code once)
# students:   https://host/submit → pick a room
# console:    https://host/r1/admin … (the admin token is shared)

# between blocks, per room: source that room's env, then the usual targets
set -a && . /etc/drone-life.env && . /etc/drone-life.d/r2.env && set +a
make reset            # talks to :8002 — HOST follows PORT
make bots N=3
make kill-prod ROOM=r2   # only room 2's containers

# siege: stop everything (a stop flushes each room's snapshot), merge, restart the big room
sudo systemctl stop drone-life@{r1,r2,r3,r4,r5} drone-life@main
sudo -iu dronelife
cd /opt/drone-life/server
set -a && . /etc/drone-life.env && . /etc/drone-life.d/main.env && set +a
uv run python -m app.roster merge --dry-run state/r1 state/r2 state/r3 state/r4 state/r5
uv run python -m app.roster merge state/r1 state/r2 state/r3 state/r4 state/r5
exit
sudo sed -i 's/^MISSION=.*/MISSION=siege/; s/^ROOMS=.*/ROOMS=/' /etc/drone-life.env
sudo systemctl start drone-life@main
# → every student opens https://host/submit; the stored token reconnects, nobody re-joins
```

`app.roster merge` seats the big room's own pilots first (whoever joined `/`
directly), then each room in the order given, re-slotting everyone from `s0`
— id, sysid, MAVLink port, pad and drone all follow the slot — and keeping
names, tokens and IPs. A name seated twice (two Sams, or one who wandered
between rooms) keeps both seats, the later one as `Sam 2`; more pilots than
`MAX_STUDENTS` is an error that names the unseated, and nothing is written.
`--dry-run` shows the seating, `--fresh` drops the big room's existing
roster, `--force` writes even if a server answers on `PORT` (it would
overwrite the file within 30 s, so the tool refuses by default). Score is
zeroed (the team total and the per-pilot points): it belongs to the round,
not the pilot. Bans are in memory only and do not carry — re-ban in the big
room's console if it comes to that. Each room's `state/<id>/rounds.jsonl`
(one line per played siege round, written at reset) stays where it is; the
merge moves rosters, not records.

`ROOMS=` is emptied for the siege so a latecomer sees the join form, not
five closed rooms; put it back the next morning.

## Footguns

- **`RunnerManager.sweep()` and `make kill-prod` are scoped by label.**
  Each room's containers carry `drone-life-room=<id>` and a room sweeps only
  its own at boot; `make kill-prod` with no `ROOM=` still takes every room's
  (`drone-life=1`) and every uvicorn on the box.
- **Every container sees every room.** `allow_host_loopback` exposes the
  whole loopback — all rooms' MAVLink ports and APIs — to every sandbox
  (DEPLOY.md, threat model). Accepted for a supervised class; the room code
  and tokens still gate everything that matters.
- **`make clean` deletes `server/state/`** — every room's roster and tokens,
  and every `rounds.jsonl`.
- **The join limiter and strike guard are per process.** A student who
  guesses wrong on three rooms burns strikes on each; `POST
  /api/v1/admin/unlock` is per room too.
- **Same code, same admin token everywhere.** Rotate both between classes,
  in the shared file only; a room file that sets its own `ROOM_CODE` fails
  preflight (one code on every projector is the promise).
- **`ROOM_ID` is a name**: lowercase letters, digits, `-`, `_`. It is a
  systemd instance, a podman label and a directory at once, so the server
  refuses anything else at boot.
