# drone-life — agent notes

Workshop co-op drone game: FastAPI/asyncio server (`server/`), Vite+TS
frontend (`web/`), podman student sandbox (`runner/`). Students fly simulated
drones with real pymavlink scripts; missions are server-side plugins.

## Commands

```bash
make test          # server pytest + web vitest — must stay green
make lint          # ruff (server); make lint-fix applies autofixes
make typecheck     # tsc --noEmit (web)
make build         # tsc + vite build
make e2e           # needs podman + `make image` — SKIP in podman-less sandboxes
make load          # timing-sensitive, local only
make dev-server    # http://localhost:8000  (MISSION=<name> selects content)
```

Server deps: `cd server && uv sync` (Python 3.12, uv-managed).
Web deps: `cd web && npm install` (Node ≥20).

## The contracts that matter

- **`docs/MISSIONS.md` is the mission contract**; the generic suite
  `server/tests/test_mission_contract.py` enforces it. New content goes in
  `server/app/game/missions/` + the registry in `missions/__init__.py`.
- **GAME text grammar (law)**: STATUSTEXT starts `GAME: `, ≤50 chars,
  positions as `N <int> E <int>` via `fmt_world`; confirmations end `!`.
- **`Mission.tile_map()` identity is process-stable** — reset() rebuilds the
  same object, never replaces it.
- **Event kinds** must be registered in `server/app/game/events.py`; the web
  HUD table is test-pinned to that file (marker block — keep its format).
- **Wire shapes**: `server/app/api/messages.py` ↔ `web/src/shared/protocol.ts`
  mirror each other; update both sides together.
- Architecture seams and bring-up order: see `CONTRIBUTING.md`.

## Gotchas

- mavutil is blocking — server-side only the generated dialect parser is
  used (`app/mav/wire.py`); MAVLink 2 everywhere (`MAVLINK20=1`).
- One event loop runs the 20 Hz sim driver and all HTTP/WS — never block it
  (file I/O on request paths → `asyncio.to_thread`).
- Gateway/API tests bind real loopback ports; a rare port-collision flake
  re-runs clean.
- `tests/support/harness.py` is the mission test harness (do not import test
  helpers from conftest).
