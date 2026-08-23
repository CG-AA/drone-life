# drone life

A one-day-workshop co-op drone game. Students write **pymavlink** scripts in
the browser; each script flies a simulated drone in one shared 200×200 m arena,
rendered live on a projector-friendly **2.5D isometric viewer**. v1 mission:
co-op crate delivery with a shared team score.

```
students' browsers ──▶ submit page ──▶ podman sandbox ──▶ MAVLink/TCP ─┐
                                                                       ▼
projector ◀── WebSocket ◀── FastAPI ◀── game engine ◀── 20 Hz kinematic sim
```

- **One Python process** (FastAPI + asyncio) hosts the sim, per-drone MAVLink
  TCP endpoints (loopback only), the mission engine, the podman script runner,
  and the web/WS API — all on **one HTTP port** (proxy-friendly).
- **Scripts are real pymavlink** against ArduPilot GUIDED-mode conventions —
  the skills transfer to real drones. A preinstalled `dronelife` helper keeps
  the beginner floor low; its source is the lesson.
- **Missions are plugins** (`server/app/game/missions/`): implement the small
  `Mission` interface, register it, done. Physics, networking, and rendering
  never change. `freefly.py` is the seam proof; `delivery.py` is v1 content.
  Select with `MISSION=<name>` (default `delivery`), e.g.
  `MISSION=rampart make dev-server`.
- **Hex-tile building** (`game/hex.py` + `tiles.py` + `building.py` +
  `blueprints.py`): missions can place material tiles on a hex grid — stacks
  are real terrain drones crash into, land on, and build with. `canyon.py`
  is pre-placed walls; `rampart.py` is guided wall-building (ferry steel from
  the quarry, `bot_builder` demos it); `forge.py` is free building where a
  closed ring of 6 clay tiles becomes a furnace.
- **Ground units** (`game/path.py` + `units.py`): creeps walk a chew-aware
  Dijkstra flow field over the tiles — walls reroute them, and what they
  can't climb they chew. `siege.py` is the payoff: tower-defense waves march
  on the Keep while drones zap creeps, squish them under tiles, and stack
  3 steel into auto-firing watchtowers (`bot_siege` demos the hunt).

## Quickstart (dev)

```bash
cd server && uv sync && cd ..            # Python 3.12 via uv
cd web && npm install && npm run build && cd ..
make dev-server                          # http://localhost:8000
make bots N=5 ADMIN_TOKEN=change-me      # five demo drones on the viewer
```

Viewer: `http://localhost:8000/` — submit page: `/submit` — instructor
console: `/admin` (needs `ADMIN_TOKEN`) — room code defaults to `classroom`
(override with `ROOM_CODE`).

Container pipeline (what students actually use): `make image`, then submit
from the browser — or `make bots N=3 MODE=container SCRIPT=bot_courier` to
watch bots play the whole game through real sandboxes. Bot scripts are
mission-specific (`bot_courier`→delivery, `bot_builder`→rampart,
`bot_siege`→siege, `bot_patrol`→any) — a bot on the wrong mission just
idles silently.

## Tests

```bash
make test       # server (pytest, incl. real-mavutil flights) + web (vitest)
make typecheck  # web: tsc --noEmit
make lint       # server: ruff check   (make lint-fix applies the autofixes)
make e2e        # real podman container completes a delivery end-to-end
make load       # 10 bots, 60 s: tick overruns <1%, world feed ≥9 Hz
```

CI (`.github/workflows/ci.yml`) runs lint + tests + typecheck + build on every
PR; `make kill-dev` / `make kill-prod` stop stray dev or prod instances.

## Layout

| path | what |
|---|---|
| `server/app/sim/` | kinematic drone sim (NED, mode machine) + `DroneBackend` seam |
| `server/app/mav/` | MAVLink gateway: TCP per drone, dispatch, telemetry |
| `server/app/game/` | engine (score/feed services) + mission plugins |
| `server/app/runner/` | podman-per-student script sandbox + live logs |
| `server/app/api/` | REST + WebSocket (viewer/student feeds) |
| `web/src/viewer/` | PixiJS isometric sky view |
| `web/src/submit/` | CodeMirror editor, run controls, live logs |
| `web/src/admin/` | instructor console: roster, kill/kick, reset, bots |
| `examples/` | `dronelife.py` helper, student templates, demo bots |
| `runner/` | Containerfile for the student-script sandbox image |
| `docs/` | STUDENT_GUIDE (handout), MISSIONS (author guide), DEPLOY (lab server + OCI proxy) |

## Gotchas we already hit for you

- mavutil is blocking: server-side only the generated dialect parser is used.
- The wire is MAVLink 2 everywhere (`MAVLINK20=1` baked into every exec path).
- `recv_match(blocking=True)` without `timeout` hangs forever — templates
  always pass timeouts.
- Script liveness = TCP close (mavutil clients don't send heartbeats).
- Rootless podman: script files must be 0644 through the uid mapping;
  `--rm` leaks on SIGKILL → the server sweeps by label at startup.
- STATUSTEXT caps at 50 chars — game messages are designed terse.
